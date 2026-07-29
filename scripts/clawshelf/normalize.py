from __future__ import annotations

from dataclasses import dataclass, field
import re


REQUIRED_FRONTMATTER = {
    "source",
    "source_type",
    "source_sha256",
    "extraction_method",
    "confidence",
}
REQUIRED_SECTIONS = {
    "Summary",
    "Paper Role in Shelf",
    "Research Question",
    "Method / Data / Setting",
    "Keywords",
    "RAG Terms",
    "Key Claims",
    "Methods or Basis",
    "Evidence Notes",
    "Limitations",
    "Axon Signals",
    "Dendrite Signals",
    "Idea Signals",
    "Connection Hooks",
    "Warnings",
}
SECTION_ALIASES = {
    "总结": "Summary",
    "文档在资料架中的作用": "Paper Role in Shelf",
    "研究问题": "Research Question",
    "方法 / 数据 / 场景": "Method / Data / Setting",
    "主题": "Topics",
    "关键词": "Keywords",
    "RAG 术语": "RAG Terms",
    "知识图谱标签": "Knowledge Map Tags",
    "关键论点": "Key Claims",
    "方法或依据": "Methods or Basis",
    "局限性": "Limitations",
    "证据备注": "Evidence Notes",
    "轴突信号": "Axon Signals",
    "树突信号": "Dendrite Signals",
    "想法信号": "Idea Signals",
    "连接": "Connection Hooks",
    "连接钩子": "Connection Hooks",
    "警告": "Warnings",
}
SUBSECTION_ALIASES = {
    "使用条件": "Use Conditions",
    "改进方向": "Improvement Directions",
}
VALID_CONFIDENCE = {"High", "Medium", "Low"}
VALID_RAG_ROLES = {"topic", "method", "dataset", "finding", "limitation", "idea_signal"}
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
SENTENCE_RE = re.compile(r"[^.!?。！？]+[.!?。！？]")
EVIDENCE_RE = re.compile(
    r"\b(evidence|source|page|pages|section|sheet|url|paragraph)\b|pp?\.|[\u4e00-\u9fff]*(证据|来源|页|章节|表格)",
    re.IGNORECASE,
)
RATIONALE_RE = re.compile(r"\b(rationale|because|inferred|推断|理由)\b", re.IGNORECASE)
SUMMARY_SUBSECTIONS = {
    "研究问题",
    "核心贡献",
    "方法 / 数据 / 场景",
    "关键发现",
    "适用条件与局限",
    "可迁移价值",
}


@dataclass(frozen=True)
class KeywordEntry:
    term: str
    evidence: str
    raw: str


@dataclass(frozen=True)
class RagTerm:
    term: str
    weight: int
    aliases: list[str]
    evidence: str
    role: str


@dataclass(frozen=True)
class SignalEntry:
    type: str
    signal: str
    evidence: str
    raw: dict[str, str]


@dataclass
class NormalizedRecord:
    frontmatter: dict[str, str]
    title: str
    sections: dict[str, str]
    keywords: list[KeywordEntry] = field(default_factory=list)
    rag_terms: list[RagTerm] = field(default_factory=list)
    axon_signals: list[SignalEntry] = field(default_factory=list)
    dendrite_signals: list[SignalEntry] = field(default_factory=list)


@dataclass
class ValidationResult:
    record: NormalizedRecord | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def parse_normalized_record(text: str) -> NormalizedRecord:
    frontmatter, body = _parse_frontmatter(text)
    title = _parse_title(body)
    sections = _parse_sections(body)
    return NormalizedRecord(
        frontmatter=frontmatter,
        title=title,
        sections=sections,
        keywords=parse_keywords(sections.get("Keywords", "")),
        rag_terms=parse_rag_terms(sections.get("RAG Terms", "")),
        axon_signals=parse_signal_entries(sections.get("Axon Signals", "")),
        dendrite_signals=parse_signal_entries(sections.get("Dendrite Signals", "")),
    )


def validate_normalized_record(text: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        record = parse_normalized_record(text)
    except ValueError as exc:
        return ValidationResult(None, [str(exc)], [])

    missing_frontmatter = sorted(REQUIRED_FRONTMATTER - set(record.frontmatter))
    if missing_frontmatter:
        errors.append(f"missing frontmatter fields: {', '.join(missing_frontmatter)}")

    confidence = record.frontmatter.get("confidence")
    if confidence and confidence not in VALID_CONFIDENCE:
        errors.append(f"invalid confidence: {confidence}")

    missing_sections = sorted(REQUIRED_SECTIONS - set(record.sections))
    if missing_sections:
        errors.append(f"missing sections: {', '.join(missing_sections)}")

    if PLACEHOLDER_RE.search(text):
        warnings.append("placeholder text remains; it should be replaced with source-metadata unknowns")

    summary = record.sections.get("Summary", "").strip()
    if summary:
        if "### " in summary:
            subsections = _parse_subsections(summary)
            missing_summary = sorted(SUMMARY_SUBSECTIONS - set(subsections))
            if missing_summary:
                errors.append(f"summary missing questions: {', '.join(missing_summary)}")
            for heading in sorted(SUMMARY_SUBSECTIONS & set(subsections)):
                if not subsections[heading].strip():
                    errors.append(f"summary question is empty: {heading}")
        else:
            sentence_count = _sentence_count(summary)
            if sentence_count < 2 or sentence_count > 4:
                errors.append(f"summary must be 2-4 sentences, found {sentence_count}")
        if len(summary) < 120:
            warnings.append("summary may be too short to cover problem, method, findings, and limits")
        if not _has_evidence(summary):
            warnings.append("summary has no explicit evidence location")

    if "Keywords" in record.sections:
        if len(record.keywords) < 8 or len(record.keywords) > 15:
            warnings.append(f"keywords contain {len(record.keywords)} entries; partial record retained")
        for keyword in record.keywords:
            if not keyword.term:
                errors.append("keyword entry has no term")
            if not _has_evidence(keyword.evidence):
                errors.append(f"keyword has no evidence: {keyword.term}")

    if "RAG Terms" in record.sections:
        if not record.rag_terms:
            warnings.append("RAG Terms section is empty; partial record retained")
        for term in record.rag_terms:
            if term.weight < 1 or term.weight > 5:
                errors.append(f"rag term weight must be 1-5: {term.term}")
            if term.role not in VALID_RAG_ROLES:
                errors.append(f"invalid rag term role for {term.term}: {term.role}")
            if not _has_evidence(term.evidence):
                errors.append(f"rag term has no evidence: {term.term}")

    for section in (
        "Key Claims",
        "Idea Signals",
        "Connection Hooks",
        "Paper Role in Shelf",
        "Research Question",
        "Method / Data / Setting",
    ):
        content = record.sections.get(section, "").strip()
        if content and not _has_evidence(content):
            errors.append(f"{section} has no explicit evidence")

    if "Limitations" in record.sections:
        errors.extend(_validate_limitations(record.sections["Limitations"]))

    if "Axon Signals" in record.sections:
        errors.extend(
            _validate_signals(
                record.axon_signals,
                "Axon Signals",
                {"Strong Contribution", "Strong Method", "Strong Limitation", "Strong Application Method"},
            )
        )

    if "Dendrite Signals" in record.sections:
        errors.extend(
            _validate_signals(
                record.dendrite_signals,
                "Dendrite Signals",
                {"Assumption", "Data / Domain Boundary", "Metric Choice", "Failure Mode", "Extension Hint"},
            )
        )

    return ValidationResult(record, errors, warnings)


def parse_keywords(section: str) -> list[KeywordEntry]:
    entries: list[KeywordEntry] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        raw = stripped[2:].strip()
        term_part, evidence = _split_keyword(raw)
        term = term_part.strip().strip("`* ")
        entries.append(KeywordEntry(term=term, evidence=evidence.strip(), raw=raw))
    return entries


def parse_rag_terms(section: str) -> list[RagTerm]:
    raw_items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in section.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- term:"):
            if current:
                raw_items.append(current)
            current = {"term": stripped.split(":", 1)[1].strip()}
            continue
        if current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = value.strip()
    if current:
        raw_items.append(current)

    terms: list[RagTerm] = []
    for item in raw_items:
        try:
            weight = int(item.get("weight", "0"))
        except ValueError:
            weight = 0
        aliases = [
            alias.strip()
            for alias in item.get("aliases", "").split(";")
            if alias.strip() and alias.strip().lower() != "none"
        ]
        terms.append(
            RagTerm(
                term=item.get("term", "").strip(),
                weight=weight,
                aliases=aliases,
                evidence=item.get("evidence", "").strip(),
                role=item.get("role", "").strip(),
            )
        )
    return terms


def parse_signal_entries(section: str) -> list[SignalEntry]:
    entries: list[SignalEntry] = []
    for item in _structured_bullets(section):
        entries.append(
            SignalEntry(
                type=item.get("type", "").strip(),
                signal=item.get("signal", "").strip(),
                evidence=(item.get("evidence", "") or item.get("rationale", "")).strip(),
                raw=item,
            )
        )
    return entries


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter")
    frontmatter: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return frontmatter, "\n".join(lines[index + 1 :])
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip()
    raise ValueError("unterminated frontmatter")


def _parse_title(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return ""


def _parse_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            current = SECTION_ALIASES.get(match.group(1), match.group(1))
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _split_keyword(raw: str) -> tuple[str, str]:
    if " — " in raw:
        return raw.split(" — ", 1)
    if " - " in raw:
        return raw.split(" - ", 1)
    if ":" in raw:
        return raw.split(":", 1)
    return raw, ""


def _has_evidence(value: str) -> bool:
    return bool(EVIDENCE_RE.search(value))


def _has_evidence_or_rationale(value: str) -> bool:
    return _has_evidence(value) or bool(RATIONALE_RE.search(value))


def _sentence_count(value: str) -> int:
    normalized = re.sub(r"`[^`]*`", "source", value)
    normalized = re.sub(r"\bpp?\.", "page", normalized, flags=re.IGNORECASE)
    return len(SENTENCE_RE.findall(normalized))


def _validate_limitations(section: str) -> list[str]:
    errors: list[str] = []
    subsections = _parse_subsections(section)
    use_conditions = subsections.get("Use Conditions", "")
    improvement_directions = subsections.get("Improvement Directions", "")
    if not use_conditions:
        errors.append("Limitations missing Use Conditions")
    if not improvement_directions:
        errors.append("Limitations missing Improvement Directions")
    if use_conditions:
        errors.extend(
            _validate_structured_bullets(
                use_conditions,
                "Use Conditions",
                ("category", "limitation", "implication"),
                ("evidence", "rationale"),
            )
        )
    if improvement_directions:
        errors.extend(
            _validate_structured_bullets(
                improvement_directions,
                "Improvement Directions",
                ("category", "direction", "expected_value"),
                ("evidence_or_rationale", "evidence", "rationale"),
            )
        )
    return errors


def _parse_subsections(section: str) -> dict[str, str]:
    subsections: dict[str, list[str]] = {}
    current: str | None = None
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            heading = stripped[4:].strip()
            current = SUBSECTION_ALIASES.get(heading, heading)
            subsections[current] = []
            continue
        if current is not None:
            subsections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in subsections.items()}


def _validate_structured_bullets(
    text: str,
    label: str,
    required_keys: tuple[str, ...],
    evidence_keys: tuple[str, ...],
) -> list[str]:
    errors: list[str] = []
    bullets = _structured_bullets(text)
    if not bullets:
        errors.append(f"Limitations {label} has no bullets")
        return errors
    for index, bullet in enumerate(bullets, start=1):
        for key in required_keys:
            if not bullet.get(key):
                errors.append(f"Limitations {label} bullet {index} missing {key}")
        evidence_value = " ".join(bullet.get(key, "") for key in evidence_keys)
        if not evidence_value:
            errors.append(f"Limitations {label} bullet {index} missing evidence_or_rationale")
        elif not _has_evidence_or_rationale(evidence_value):
            errors.append(f"Limitations {label} bullet {index} has no evidence or rationale")
    return errors


def _validate_signals(entries: list[SignalEntry], label: str, valid_types: set[str]) -> list[str]:
    errors: list[str] = []
    if not entries:
        errors.append(f"{label} has no structured signal entries")
        return errors
    seen_types = {entry.type for entry in entries if entry.type}
    missing_types = sorted(valid_types - seen_types)
    if missing_types:
        errors.append(f"{label} missing signal types: {', '.join(missing_types)}")
    for index, entry in enumerate(entries, start=1):
        if not entry.type:
            errors.append(f"{label} entry {index} missing type")
        elif entry.type not in valid_types:
            errors.append(f"{label} entry {index} has invalid type: {entry.type}")
        if not entry.signal:
            errors.append(f"{label} entry {index} missing signal")
        if not entry.evidence:
            errors.append(f"{label} entry {index} missing evidence")
        elif not _has_evidence_or_rationale(entry.evidence):
            errors.append(f"{label} entry {index} has no evidence or rationale")
    return errors


def _structured_bullets(text: str) -> list[dict[str, str]]:
    bullets: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current:
                bullets.append(current)
            current = {}
            stripped = stripped[2:].strip()
        if current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = value.strip()
    if current:
        bullets.append(current)
    return bullets
