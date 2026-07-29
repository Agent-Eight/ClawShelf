from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
import os
import re

from .extractors import ExtractorRegistry
from .config import ShelfConfig, load_or_create_config
from .keyword_worker import (
    KeywordExtraction,
    KeywordExtractionPacket,
    KeywordWorker,
    KeywordWorkerError,
    KeywordValidationError,
    SectionEvidence,
    run_openclaw_keyword_worker,
)
from .models import ExtractionResult, ProcessingWarning, source_record
from .normalize import REQUIRED_SECTIONS, parse_normalized_record, validate_normalized_record


MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")
SECTION_INPUT_BUDGET = 24_000
NORMALIZER_REVISION = "canonical-evidence-creativity"
CHECKPOINT_VERSION = 1
SUPPORTED_SOURCE_SUFFIXES = {".md", ".txt", ".pdf", ".xlsx"}
IGNORED_SOURCE_DIRS = {".git", ".hg", ".svn", ".venv", "__pycache__", "clawshelf"}
PRIORITY_SECTION_ROLES = (
    "abstract",
    "introduction",
    "method / data / setting",
    "results / findings",
    "discussion / limitations",
    "conclusion / implications",
)
EXCLUDED_SECTION_ROLES = {"references", "acknowledgments", "appendix"}
HEADING_ALIASES = {
    "Summary": ("Summary", "总结"),
    "Topics": ("Topics", "主题"),
}


@dataclass(frozen=True)
class AutoNormalizeResult:
    source: Path
    record_path: Path | None
    status: str
    warnings: list[str]
    coverage: str = "full"


@dataclass(frozen=True)
class ParsedSection:
    heading: str
    heading_path: tuple[str, ...]
    role: str
    text: str


@dataclass(frozen=True)
class SectionSelection:
    sections: list[SectionEvidence]
    warnings: list[str]


def normalize_sources(
    folder: Path,
    sources: list[Path],
    keyword_worker: KeywordWorker | None = None,
    keyword_model: str | None = None,
    config: ShelfConfig | None = None,
) -> list[AutoNormalizeResult]:
    root = folder.resolve()
    config = config or load_or_create_config(root)
    normalized_dir = root / "clawshelf" / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    results: list[AutoNormalizeResult] = []
    registry = ExtractorRegistry()
    for source in sorted({path.resolve() for path in sources}):
        if not source.is_file():
            continue
        try:
            extraction_method = registry.expected_extraction_method(source)
            if extraction_method is None:
                results.append(AutoNormalizeResult(source, None, "unsupported", [f"unsupported source type: {source.suffix}"], "none"))
                continue
            record_path = _record_path_for_source(root, normalized_dir, source)
            fingerprint = source_record(source)
            if _existing_current_record(record_path, fingerprint.sha256, extraction_method, config.shelf_plan_fingerprint):
                results.append(AutoNormalizeResult(source, record_path, "current", [], _record_coverage(record_path)))
                continue
            checkpoint_dir = _checkpoint_dir(root, fingerprint.sha256)
            # A stale canonical record is intentionally rebuilt from the source;
            # checkpoints are only for jobs that never reached canonical output.
            extraction = None if record_path.exists() else _load_cached_extraction(
                checkpoint_dir, fingerprint.sha256, extraction_method
            )
            if extraction is None:
                extraction = registry.extract(source)
                if extraction is not None:
                    _save_cached_extraction(checkpoint_dir, extraction)
            if extraction is None:
                results.append(AutoNormalizeResult(source, None, "unsupported", [f"unsupported source type: {source.suffix}"], "none"))
                continue
            text, warnings = _render_record(root, source, extraction, keyword_worker, keyword_model, config, checkpoint_dir)
        except KeywordValidationError as exc:
            results.append(AutoNormalizeResult(source, None, "validation_failed", [str(exc)], "none"))
            continue
        except KeywordWorkerError as exc:
            results.append(AutoNormalizeResult(source, None, "llm_unavailable", [str(exc)], "none"))
            continue
        except Exception as exc:
            results.append(AutoNormalizeResult(source, None, "failed", [str(exc)], "none"))
            continue
        validation = validate_normalized_record(text)
        if not validation.valid:
            results.append(AutoNormalizeResult(source, None, "invalid", warnings + validation.errors + validation.warnings, "none"))
            continue
        record_path.write_text(text, encoding="utf-8")
        results.append(
            AutoNormalizeResult(
                source,
                record_path,
                "normalized",
                warnings + validation.warnings,
                _coverage_from_warnings(warnings),
            )
        )
    _write_metadata(root, config)
    return results


def _checkpoint_dir(root: Path, source_sha256: str) -> Path:
    return root / "clawshelf" / "normalization-jobs" / source_sha256


def _load_cached_extraction(
    checkpoint_dir: Path, source_sha256: str, extraction_method: str
) -> ExtractionResult | None:
    path = checkpoint_dir / "extraction.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != CHECKPOINT_VERSION:
            return None
        if data.get("source_sha256") != source_sha256 or data.get("extraction_method") != extraction_method:
            return None
        source = data["source"]
        return ExtractionResult(
            source=source_record(Path(source["path"])),
            extraction_method=extraction_method,
            content=str(data["content"]),
            warnings=[ProcessingWarning(**warning) for warning in data.get("warnings", [])],
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_cached_extraction(checkpoint_dir: Path, extraction: ExtractionResult) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(
        checkpoint_dir / "extraction.json",
        {
            "version": CHECKPOINT_VERSION,
            "source_sha256": extraction.source.sha256,
            "extraction_method": extraction.extraction_method,
            "source": {"path": extraction.source.path},
            "content": extraction.content,
            "warnings": [{"code": warning.code, "message": warning.message} for warning in extraction.warnings],
        },
    )


def _atomic_json_write(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _existing_current_record(record_path: Path, source_sha256: str, extraction_method: str, shelf_plan_fingerprint: str = "") -> bool:
    if not record_path.is_file():
        return False
    try:
        text = record_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if _frontmatter_value(text, "source_sha256") != source_sha256:
        return False
    if _frontmatter_value(text, "extraction_method") != extraction_method:
        return False
    if _frontmatter_value(text, "normalizer_revision") != NORMALIZER_REVISION:
        return False
    if shelf_plan_fingerprint and _frontmatter_value(text, "shelf_plan_fingerprint") != shelf_plan_fingerprint:
        return False
    try:
        record = parse_normalized_record(text)
    except ValueError:
        return False
    return REQUIRED_SECTIONS <= set(record.sections) and validate_normalized_record(text).valid


def discover_sources(folder: Path) -> list[Path]:
    root = folder.resolve()
    if not root.is_dir():
        return []
    return sorted(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
        and not path.name.startswith(".")
        and not any(part in IGNORED_SOURCE_DIRS for part in path.relative_to(root).parts)
    )


def stale_sources(folder: Path, config: ShelfConfig | None = None) -> list[Path]:
    root = folder.resolve()
    config = config or load_or_create_config(root)
    normalized_dir = root / "clawshelf" / "normalized"
    registry = ExtractorRegistry()
    stale: list[Path] = []
    for source in discover_sources(root):
        extraction_method = registry.expected_extraction_method(source)
        if extraction_method is None:
            continue
        record_path = _record_path_for_source(root, normalized_dir, source)
        if not _existing_current_record(record_path, source_record(source).sha256, extraction_method, config.shelf_plan_fingerprint):
            stale.append(source)
    return stale


def _render_record(
    root: Path,
    source: Path,
    extraction: ExtractionResult,
    keyword_worker: KeywordWorker | None,
    keyword_model: str | None,
    config: ShelfConfig,
    checkpoint_dir: Path,
) -> tuple[str, list[str]]:
    rel_source = _relative_source(root, source)
    title = _title_from_content(source, extraction.content)
    selection = _select_sections(extraction.content)
    content_warnings = list(selection.warnings)
    sections = selection.sections
    if not sections:
        content_warnings.append("No extractable text was found; record is limited to extraction metadata.")
        sections = [
            SectionEvidence(
                heading="Extraction metadata",
                heading_path="Extraction metadata",
                role="extraction metadata",
                text=source.stem.replace("_", " "),
            )
        ]
    content_warning = " ".join(content_warnings)
    packet = _keyword_packet(rel_source, title, sections, content_warning, config.shelf_plan)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(checkpoint_dir / "packet.json", packet.to_payload())
    worker = keyword_worker or _default_keyword_worker()
    model = keyword_model or os.environ.get("CLAWSHELF_KEYWORD_MODEL") or ""
    extracted = _run_keyword_worker(worker, packet, model, checkpoint_dir)
    confidence = "High" if extraction.content.strip() and not extraction.warnings else "Medium"
    warnings = [warning.message for warning in extraction.warnings]
    warnings.extend(content_warnings)
    warnings.extend(extracted.warnings)
    coverage = _coverage_from_warnings(content_warnings)

    title = extracted.title or title
    topic_lines = _bullet_lines(extracted.topics)
    keyword_lines = _keyword_lines(extracted)
    rag_lines = _rag_lines(extracted)
    claims = _bullet_lines(extracted.key_claims)
    limits = _limitation_lines(extracted)
    axon_signals = _signal_lines(extracted.axon_signals)
    dendrite_signals = _signal_lines(extracted.dendrite_signals)
    idea_signals = _bullet_lines(extracted.idea_signals)
    connection_hooks = _bullet_lines(extracted.connection_hooks)
    evidence_notes = _bullet_lines([f"Original source: `{rel_source}`", *extracted.evidence_notes])
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- None."

    record = f"""---
source: {rel_source}
source_type: {extraction.source.source_type}
source_sha256: {extraction.source.sha256}
extraction_method: {extraction.extraction_method}
normalizer_revision: {NORMALIZER_REVISION}
coverage: {coverage}
confidence: {confidence}
shelf_plan_fingerprint: {config.shelf_plan_fingerprint}
shelf_plan_tags: {_shelf_plan_tags(config)}
---

# {title}

## 总结

{extracted.summary}

## 文档在资料架中的作用

{extracted.paper_role}

## 研究问题

{extracted.research_question}

## 方法 / 数据 / 场景

{extracted.method_data_setting}

## 主题

{topic_lines}

## 关键词

{keyword_lines}

## RAG 术语

{rag_lines}

## 知识图谱标签

- Domain: {config.shelf_plan['domain_background']}
- Direction: {config.shelf_plan['work_direction']}
- Problem fit: {config.shelf_plan['concrete_problem']}
- Companion mode: {config.shelf_plan['companion_mode']}
- Map role: evidence

## 关键论点

{claims}

## 方法或依据

{extracted.methods_or_basis}

## 局限性

{limits}

## 轴突信号

{axon_signals}

## 树突信号

{dendrite_signals}

## 证据备注

{evidence_notes}

## 想法信号

{idea_signals}

## 连接钩子

{connection_hooks}

## 警告

{warning_lines}
"""
    record, placeholder_count = _replace_record_placeholders(record)
    if placeholder_count:
        warning = (
            f"Replaced {placeholder_count} angle-bracket placeholder"
            f"{'s' if placeholder_count != 1 else ''} with source-metadata unknown."
        )
        record = record.replace("\n## 警告\n\n", f"\n## 警告\n\n- {warning}\n", 1)
        warnings.append(warning)
    return record, warnings


def _default_keyword_worker() -> KeywordWorker:
    def run(packet: KeywordExtractionPacket, model: str, *, checkpoint_dir: Path | None = None) -> KeywordExtraction:
        return run_openclaw_keyword_worker(
            packet,
            model,
            openclaw_bin=os.environ.get("CLAWSHELF_OPENCLAW_BIN", "openclaw"),
            session_key=os.environ.get("OPENCLAW_SESSION_KEY"),
            agent_id=os.environ.get("OPENCLAW_AGENT_ID"),
            channel=os.environ.get("OPENCLAW_CHANNEL", "last"),
            checkpoint_dir=checkpoint_dir,
        )

    return run


def _run_keyword_worker(
    worker: KeywordWorker,
    packet: KeywordExtractionPacket,
    model: str,
    checkpoint_dir: Path,
) -> KeywordExtraction:
    try:
        supports_checkpoint = "checkpoint_dir" in inspect.signature(worker).parameters
    except (TypeError, ValueError):
        supports_checkpoint = False
    if supports_checkpoint:
        return worker(packet, model, checkpoint_dir=checkpoint_dir)  # type: ignore[call-arg]
    return worker(packet, model)


def _replace_record_placeholders(record: str) -> tuple[str, int]:
    return PLACEHOLDER_RE.subn("unknown (source: extraction metadata)", record)


def _coverage_from_warnings(warnings: list[str]) -> str:
    partial_markers = (
        "Section input exceeded",
        "Document text exceeded",
        "No usable Markdown heading hierarchy",
        "No extractable text was found",
    )
    return "partial" if any(warning.startswith(partial_markers) for warning in warnings) else "full"


def _record_coverage(record_path: Path) -> str:
    try:
        coverage = _frontmatter_value(record_path.read_text(encoding="utf-8", errors="replace"), "coverage")
    except OSError:
        return "full"
    return coverage if coverage in {"full", "partial"} else "full"


def _keyword_packet(
    rel_source: str,
    title: str,
    sections: list[SectionEvidence],
    content_warning: str,
    shelf_plan: dict[str, str],
) -> KeywordExtractionPacket:
    return KeywordExtractionPacket(
        source=rel_source,
        title=title,
        content_warning=content_warning,
        section_packets=sections,
        shelf_plan=shelf_plan,
    )


def _bullet_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _keyword_lines(extracted: KeywordExtraction) -> str:
    return "\n".join(
        f"- `{keyword.term}` — {keyword.why}; evidence: {keyword.evidence}"
        for keyword in extracted.keywords
    )


def _rag_lines(extracted: KeywordExtraction) -> str:
    return "\n\n".join(
        "\n".join(
            [
                f"- term: {term.term}",
                f"  weight: {term.weight}",
                f"  aliases: {'; '.join(term.aliases) if term.aliases else 'none'}",
                f"  evidence: {term.evidence}",
                f"  role: {term.role}",
            ]
        )
        for term in extracted.rag_terms
    )


def _limitation_lines(extracted: KeywordExtraction) -> str:
    use_conditions = "\n\n".join(
        "\n".join(
            [
                f"- category: {item.category}",
                f"  limitation: {item.limitation}",
                f"  implication: {item.implication}",
                f"  evidence: {item.evidence}",
            ]
        )
        for item in extracted.use_conditions
    )
    improvement_directions = "\n\n".join(
        "\n".join(
            [
                f"- category: {item.category}",
                f"  direction: {item.direction}",
                f"  expected_value: {item.expected_value}",
                f"  evidence_or_rationale: {item.evidence_or_rationale}",
            ]
        )
        for item in extracted.improvement_directions
    )
    return f"""### 使用条件

{use_conditions}

### 改进方向

{improvement_directions}"""


def _signal_lines(signals: list) -> str:
    return "\n".join(
        "\n".join(
            [
                f"- type: {signal.type}",
                f"  signal: {signal.signal}",
                f"  evidence: {signal.evidence}",
            ]
        )
        for signal in signals
    )


def _select_sections(content: str, budget: int = SECTION_INPUT_BUDGET) -> SectionSelection:
    stripped = content.strip()
    if not stripped:
        return SectionSelection([], [])

    parsed = _parse_markdown_sections(stripped)
    if not parsed:
        text, truncated = _truncate_at_paragraph(stripped, budget)
        warnings = ["No usable Markdown heading hierarchy was detected; normalized as one Document section."]
        if truncated:
            warnings.append(f"Document text exceeded the {budget}-character section budget and was truncated.")
        return SectionSelection(
            [SectionEvidence("Document", "Document", "document", text)],
            warnings,
        )

    if sum(_section_size(section) for section in parsed) <= budget:
        return SectionSelection([_section_evidence(section) for section in parsed], [])

    eligible = [
        (index, section)
        for index, section in enumerate(parsed)
        if section.role not in EXCLUDED_SECTION_ROLES
    ]
    selected_indexes: set[int] = set()
    used = 0

    def add_if_fits(index: int, section: ParsedSection) -> bool:
        nonlocal used
        size = _section_size(section)
        if index in selected_indexes or used + size > budget:
            return False
        selected_indexes.add(index)
        used += size
        return True

    for role in PRIORITY_SECTION_ROLES:
        for index, section in eligible:
            if section.role == role and add_if_fits(index, section):
                break

    for index, section in eligible:
        add_if_fits(index, section)

    if not selected_indexes and eligible:
        index, section = eligible[0]
        allowance = max(1, budget - len(" > ".join(section.heading_path)) - len(section.role))
        text, _ = _truncate_at_paragraph(section.text, allowance)
        selected = [
            SectionEvidence(
                heading=section.heading,
                heading_path=" > ".join(section.heading_path),
                role=section.role,
                text=text,
            )
        ]
    else:
        selected = [
            _section_evidence(section)
            for index, section in enumerate(parsed)
            if index in selected_indexes
        ]

    eligible_count = len(eligible)
    omitted = eligible_count - len(selected)
    excluded = len(parsed) - eligible_count
    warning = (
        f"Section input exceeded the {budget}-character budget; selected "
        f"{len(selected)} of {eligible_count} eligible Level-1 sections and omitted {omitted}."
    )
    if excluded:
        warning += f" Excluded {excluded} reference/appendix sections."
    return SectionSelection(selected, [warning])


def _parse_markdown_sections(content: str) -> list[ParsedSection]:
    lines = content.splitlines()
    headings: list[tuple[int, int, str]] = []
    fence_marker = ""
    for line_number, line in enumerate(lines):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if not fence_marker:
                fence_marker = marker
            elif fence_marker == marker:
                fence_marker = ""
            continue
        match = None if fence_marker else MARKDOWN_HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        heading = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
        headings.append((line_number, level, heading))

    if not headings:
        return []

    # The first H1 is document metadata. Main body packets are the first
    # heading level beneath it (normally H2), with nested headings retained
    # inside their parent packet instead of becoming separate evidence units.
    title_index = headings[0][0] if headings[0][1] == 1 else -1
    body_headings = [heading for heading in headings if heading[0] > title_index]
    if not body_headings:
        return []
    main_level = min(level for _, level, _ in body_headings)
    main_headings = [heading for heading in body_headings if heading[1] == main_level]
    if not main_headings:
        return []

    sections: list[ParsedSection] = []
    first_main_line = main_headings[0][0]

    # Some converters put Abstract below author metadata at H3-H6. Preserve a
    # leading abstract as its own main-body packet before the first true H2.
    for line_number, _level, heading in body_headings:
        if line_number >= first_main_line:
            break
        if _section_role(heading) == "abstract":
            text = "\n".join(lines[line_number + 1 : first_main_line]).strip()
            if text:
                sections.append(ParsedSection(heading, (heading,), "abstract", text))
            break

    for index, (line_number, _level, heading) in enumerate(main_headings):
        next_line = main_headings[index + 1][0] if index + 1 < len(main_headings) else len(lines)
        text = "\n".join(lines[line_number + 1 : next_line]).strip()
        if text:
            sections.append(ParsedSection(heading, (heading,), _section_role(heading), text))
    return sections


def _section_role(heading: str) -> str:
    plain_heading = re.sub(r"[*_`]", "", heading).strip()
    normalized = plain_heading.casefold()
    if any(term in normalized for term in ("reference", "bibliograph", "参考文献")):
        return "references"
    if any(term in normalized for term in ("acknowledg", "致谢")):
        return "acknowledgments"
    if re.match(r"^(?:appendix\b|[A-Z]\b|附录)", plain_heading, re.IGNORECASE):
        return "appendix"
    if any(term in normalized for term in ("abstract", "summary", "摘要", "总结")):
        return "abstract"
    if any(term in normalized for term in ("intro", "background", "motivation", "引言", "背景")):
        return "introduction"
    if any(term in normalized for term in ("method", "model", "data", "setup", "experiment", "approach", "方法", "数据")):
        return "method / data / setting"
    if any(term in normalized for term in ("result", "finding", "evaluation", "empirical", "结果", "发现", "实证")):
        return "results / findings"
    if any(term in normalized for term in ("discussion", "limitation", "caveat", "future", "讨论", "局限")):
        return "discussion / limitations"
    if any(term in normalized for term in ("conclusion", "implication", "结论", "启示")):
        return "conclusion / implications"
    return "section"


def _section_size(section: ParsedSection) -> int:
    return len(section.text) + len(" > ".join(section.heading_path)) + len(section.role)


def _section_evidence(section: ParsedSection) -> SectionEvidence:
    return SectionEvidence(
        heading=section.heading,
        heading_path=" > ".join(section.heading_path),
        role=section.role,
        text=section.text,
    )


def _truncate_at_paragraph(text: str, budget: int) -> tuple[str, bool]:
    stripped = text.strip()
    if len(stripped) <= budget:
        return stripped, False
    suffix = "\n\n[truncated]"
    prefix = stripped[: max(1, budget - len(suffix))]
    cut = prefix.rfind("\n\n")
    if cut < max(1, len(prefix) // 2):
        cut = prefix.rfind("\n")
    if cut < max(1, len(prefix) // 2):
        cut = prefix.rfind(" ")
    if cut > 0:
        prefix = prefix[:cut]
    return prefix.rstrip() + suffix, True


def _title_from_content(source: Path, content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip(" #\t")
        if 8 <= len(stripped) <= 160 and not stripped.lower().startswith(("page ", "abstract", "keywords")):
            return _clean_title(stripped)
    return _clean_title(source.stem.replace("_", " ").replace("-", " "))


def _clean_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned[:140] or "Untitled source"


def _slug_for_source(source: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", source.stem.lower()).strip("-")
    return stem[:100] or "source"


def _record_path_for_source(root: Path, normalized_dir: Path, source: Path) -> Path:
    base = normalized_dir / f"{_slug_for_source(source)}.md"
    if not base.exists():
        return base
    text = base.read_text(encoding="utf-8", errors="replace")
    if _frontmatter_value(text, "source") == _relative_source(root, source):
        return base
    relative = _relative_source(root, source)
    suffix = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:8]
    return normalized_dir / f"{_slug_for_source(source)}-{suffix}.md"


def _relative_source(root: Path, source: Path) -> str:
    try:
        return str(source.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(source.resolve())


def _write_metadata(root: Path, config: ShelfConfig | None = None) -> None:
    config = config or load_or_create_config(root)
    clawshelf = root / "clawshelf"
    normalized = clawshelf / "normalized"
    records = sorted(normalized.glob("*.md")) if normalized.is_dir() else []
    rows = [
        "# ClawShelf Metadata - Auto-normalized watcher shelf",
        "",
        f"- Collection: `{root}`",
        f"- Documents: {len(records)}",
        f"- Shelf Plan: {_shelf_plan_tags(config)}",
        "",
        "| id | source | title | type | topics | summary | confidence |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, record in enumerate(records, start=1):
        text = record.read_text(encoding="utf-8", errors="replace")
        source = _frontmatter_value(text, "source")
        source_type = _frontmatter_value(text, "source_type")
        confidence = _frontmatter_value(text, "confidence")
        title = _title_value(text)
        topics = ", ".join(_topic_values(text)[:3])
        summary_lines = _section_value(text, "Summary").splitlines()
        summary = summary_lines[0][:160] if summary_lines else ""
        rows.append(
            f"| {index} | `{source}` | {title} | {source_type} | {topics} | {summary} | {confidence} |"
        )
    rows.extend(["", "## Knowledge Map Summary", "", "- Source clusters: generated from normalized RAG terms during watcher comparison.", "- Gaps: deeper synthesis is deferred until the owner asks for review.", ""])
    clawshelf.mkdir(parents=True, exist_ok=True)
    (clawshelf / "clawshelf-metadata.md").write_text("\n".join(rows), encoding="utf-8")


def _shelf_plan_tags(config: ShelfConfig) -> str:
    return " / ".join(config.shelf_plan[field] for field in ("domain_background", "work_direction", "concrete_problem", "companion_mode"))


def _frontmatter_value(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _title_value(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip().replace("|", "\\|")
    return ""


def _topic_values(text: str) -> list[str]:
    section = _section_value(text, "Topics")
    return [line[2:].strip().replace("|", "\\|") for line in section.splitlines() if line.startswith("- ")]


def _section_value(text: str, heading: str) -> str:
    match = None
    for candidate in HEADING_ALIASES.get(heading, (heading,)):
        pattern = re.compile(rf"^## {re.escape(candidate)}\s*$", re.MULTILINE)
        match = pattern.search(text)
        if match:
            break
    if not match:
        return ""
    next_match = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(text)
    return text[match.end() : end].strip().replace("|", "\\|")
