from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Protocol


VALID_RAG_ROLES = {"topic", "method", "dataset", "finding", "limitation", "idea_signal"}
VALID_AXON_TYPES = {"Strong Contribution", "Strong Method", "Strong Limitation", "Strong Application Method"}
VALID_DENDRITE_TYPES = {"Assumption", "Data / Domain Boundary", "Metric Choice", "Failure Mode", "Extension Hint"}
VALID_LIMITATION_CATEGORIES = {
    "Scope Boundaries",
    "Data / Evidence Limits",
    "Method / Assumption Limits",
    "Evaluation Limits",
    "Generalization Limits",
    "Practical Use Limits",
    "Uncertainty / Conflicting Evidence",
    "Extraction / Review Limits",
}
BAD_TERM_RE = re.compile(
    r"\b("
    r"arxiv|latex|class files?|creative commons|published|cambridge university press|"
    r"department|university|school|institute|author|authors?|email|http|www|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"what|where|when|known|same|their|they|those|one|all"
    r")\b",
    re.IGNORECASE,
)
OCR_FRAGMENT_RE = re.compile(r"\b(nancial|nance|erential|scienti|ddress|conom|rst|los)\b", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")
UNKNOWN_SOURCE_TEXT = "unknown (source: extraction metadata)"


class KeywordWorkerError(RuntimeError):
    pass


MAX_KEYWORD_REPAIR_ATTEMPTS = 3
KEYWORD_CONTRACT_FINGERPRINT = hashlib.sha256(
    b"clawshelf-keyword-canonical-paper-role-evidence-merge-patch"
).hexdigest()


class KeywordQualityError(KeywordWorkerError):
    pass


class KeywordValidationError(KeywordWorkerError):
    pass


@dataclass(frozen=True)
class SectionEvidence:
    heading: str
    heading_path: str
    role: str
    text: str


@dataclass(frozen=True)
class KeywordExtractionPacket:
    source: str
    title: str
    content_warning: str
    section_packets: list[SectionEvidence]
    shelf_plan: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "content_warning": self.content_warning,
            "shelf_plan": self.shelf_plan,
            "section_packets": [
                {
                    "heading": section.heading,
                    "heading_path": section.heading_path,
                    "role": section.role,
                    "evidence_ref": f"section: {section.heading_path}",
                    "text": section.text,
                }
                for section in self.section_packets
            ],
        }


@dataclass(frozen=True)
class KeywordSignal:
    term: str
    why: str
    evidence: str


@dataclass(frozen=True)
class RagSignal:
    term: str
    weight: int
    aliases: list[str]
    evidence: str
    role: str


@dataclass(frozen=True)
class StructuredSignal:
    type: str
    signal: str
    evidence: str


@dataclass(frozen=True)
class LimitationUseCondition:
    category: str
    limitation: str
    implication: str
    evidence: str


@dataclass(frozen=True)
class LimitationImprovement:
    category: str
    direction: str
    expected_value: str
    evidence_or_rationale: str


@dataclass(frozen=True)
class KeywordExtraction:
    title: str
    summary: str
    paper_role: str
    research_question: str
    method_data_setting: str
    topics: list[str]
    keywords: list[KeywordSignal]
    rag_terms: list[RagSignal]
    key_claims: list[str]
    methods_or_basis: str
    use_conditions: list[LimitationUseCondition]
    improvement_directions: list[LimitationImprovement]
    axon_signals: list[StructuredSignal]
    dendrite_signals: list[StructuredSignal]
    idea_signals: list[str]
    connection_hooks: list[str]
    evidence_notes: list[str]
    warnings: list[str] = field(default_factory=list)
    model: str = ""


class KeywordWorker(Protocol):
    def __call__(self, packet: KeywordExtractionPacket, model: str) -> KeywordExtraction:
        ...


def parse_keyword_extraction(text: str, model: str = "") -> KeywordExtraction:
    try:
        data = json.loads(_extract_json_object(text))
    except json.JSONDecodeError as exc:
        raise KeywordWorkerError(f"invalid keyword worker JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise KeywordWorkerError("keyword worker response must be a JSON object")

    cleanup_warnings: list[str] = []
    keywords = _filtered_keywords(data, cleanup_warnings)
    rag_terms = _filtered_rag_terms(data, cleanup_warnings)
    if len(keywords) < 8:
        cleanup_warnings.append(f"Retained {len(keywords)} valid keywords after term validation; partial record retained.")
    if not rag_terms:
        cleanup_warnings.append("No valid RAG terms remained after term validation; partial record retained.")

    result = KeywordExtraction(
        title=_required_str(data, "title"),
        summary=_summary_text(data),
        paper_role=_paper_role(data),
        research_question=_required_str(data, "research_question"),
        method_data_setting=_required_str(data, "method_data_setting"),
        topics=_string_list(data, "topics", minimum=1),
        keywords=keywords,
        rag_terms=rag_terms,
        key_claims=_string_list(data, "key_claims", minimum=1),
        methods_or_basis=_required_str_with_fallback(data, "methods_or_basis", "method_data_setting"),
        use_conditions=[_use_condition(item) for item in _object_list(data, "use_conditions", minimum=1)],
        improvement_directions=[
            _improvement(item) for item in _object_list(data, "improvement_directions", minimum=1)
        ],
        axon_signals=[_signal(item, VALID_AXON_TYPES, "axon_signals") for item in _object_list(data, "axon_signals", minimum=4)],
        dendrite_signals=[
            _signal(item, VALID_DENDRITE_TYPES, "dendrite_signals")
            for item in _object_list(data, "dendrite_signals", minimum=5)
        ],
        idea_signals=_string_list(data, "idea_signals", minimum=1),
        connection_hooks=_string_list(data, "connection_hooks", minimum=1),
        evidence_notes=_string_list(data, "evidence_notes", minimum=1),
        warnings=_string_list(data, "warnings", minimum=0),
        model=str(data.get("model") or model or ""),
    )
    result = _replace_narrative_placeholders(result, cleanup_warnings)
    result = replace(result, warnings=[*result.warnings, *cleanup_warnings])
    validate_keyword_extraction(result)
    return result


def _summary_text(data: dict) -> str:
    value = data.get("summary")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, dict):
        raise KeywordWorkerError("summary must be a non-empty string or object")
    fields = [
        ("研究问题", "research_problem"),
        ("核心贡献", "core_contribution"),
        ("方法 / 数据 / 场景", "method_data_setting"),
        ("关键发现", "key_findings"),
        ("适用条件与局限", "use_conditions_and_limits"),
        ("可迁移价值", "transferable_value"),
    ]
    lines: list[str] = []
    for label, key in fields:
        lines.append(f"### {label}")
        lines.append("")
        lines.append(_summary_field(value.get(key), key))
        lines.append("")
    return "\n".join(lines).strip()


def _paper_role(data: dict) -> str:
    value = _as_dict(data.get("paper_role"), "paper_role")
    role = value.get("value")
    if not isinstance(role, str) or not role.strip():
        raise KeywordWorkerError("paper_role.value must be a non-empty string")
    evidence = value.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise KeywordWorkerError(
            "paper_role.evidence must be a non-empty string"
        )
    role = role.strip()
    evidence = evidence.strip()
    _require_evidence(evidence, "paper_role.evidence")
    return f"{role} (evidence: {evidence})"


def _filtered_keywords(data: dict, warnings: list[str]) -> list[KeywordSignal]:
    keywords: list[KeywordSignal] = []
    for item in _object_list(data, "keywords", minimum=0, maximum=15):
        label = _term_label(item, "keyword")
        try:
            keyword = _keyword(item)
            _validate_term(keyword.term, "keyword")
            _require_evidence(keyword.evidence, f"keyword {keyword.term}")
        except KeywordWorkerError as exc:
            warnings.append(f"Skipped keyword `{label}`: {exc}.")
            continue
        keywords.append(keyword)
    return keywords


def _filtered_rag_terms(data: dict, warnings: list[str]) -> list[RagSignal]:
    rag_terms: list[RagSignal] = []
    for item in _object_list(data, "rag_terms", minimum=0, maximum=6):
        label = _term_label(item, "RAG term")
        try:
            term = _rag_term(item)
            _validate_term(term.term, "rag term")
            if term.weight < 1 or term.weight > 5:
                raise KeywordQualityError(f"rag term weight must be 1-5: {term.term}")
            if term.role not in VALID_RAG_ROLES:
                raise KeywordQualityError(f"invalid rag term role for {term.term}: {term.role}")
            _require_evidence(term.evidence, f"rag term {term.term}")
        except KeywordWorkerError as exc:
            warnings.append(f"Skipped RAG term `{label}`: {exc}.")
            continue
        rag_terms.append(term)
    return rag_terms


def _term_label(item: object, fallback: str) -> str:
    if isinstance(item, dict) and isinstance(item.get("term"), str) and item["term"].strip():
        return item["term"].strip().replace("`", "'")
    return fallback


def _replace_narrative_placeholders(
    result: KeywordExtraction,
    warnings: list[str],
) -> KeywordExtraction:
    """Replace model placeholders without relaxing structural enum validation."""
    replaced_fields: list[str] = []

    def clean(value: str, field_name: str) -> str:
        if not PLACEHOLDER_RE.search(value):
            return value
        replaced_fields.append(field_name)
        return PLACEHOLDER_RE.sub(UNKNOWN_SOURCE_TEXT, value)

    cleaned = replace(
        result,
        title=clean(result.title, "title"),
        summary=clean(result.summary, "summary"),
        paper_role=clean(result.paper_role, "paper_role"),
        research_question=clean(result.research_question, "research_question"),
        method_data_setting=clean(result.method_data_setting, "method_data_setting"),
        topics=[clean(value, "topics") for value in result.topics],
        keywords=[
            replace(keyword, why=clean(keyword.why, "keyword explanation"), evidence=clean(keyword.evidence, "keyword evidence"))
            for keyword in result.keywords
        ],
        rag_terms=[
            replace(
                term,
                aliases=[clean(alias, "RAG alias") for alias in term.aliases],
                evidence=clean(term.evidence, "RAG evidence"),
            )
            for term in result.rag_terms
        ],
        key_claims=[clean(value, "key_claims") for value in result.key_claims],
        methods_or_basis=clean(result.methods_or_basis, "methods_or_basis"),
        use_conditions=[
            replace(
                item,
                limitation=clean(item.limitation, "use-condition limitation"),
                implication=clean(item.implication, "use-condition implication"),
                evidence=clean(item.evidence, "use-condition evidence"),
            )
            for item in result.use_conditions
        ],
        improvement_directions=[
            replace(
                item,
                direction=clean(item.direction, "improvement direction"),
                expected_value=clean(item.expected_value, "improvement expected value"),
                evidence_or_rationale=clean(item.evidence_or_rationale, "improvement evidence"),
            )
            for item in result.improvement_directions
        ],
        axon_signals=[
            replace(signal, signal=clean(signal.signal, "axon signal"), evidence=clean(signal.evidence, "axon evidence"))
            for signal in result.axon_signals
        ],
        dendrite_signals=[
            replace(signal, signal=clean(signal.signal, "dendrite signal"), evidence=clean(signal.evidence, "dendrite evidence"))
            for signal in result.dendrite_signals
        ],
        idea_signals=[clean(value, "idea_signals") for value in result.idea_signals],
        connection_hooks=[clean(value, "connection_hooks") for value in result.connection_hooks],
        evidence_notes=[clean(value, "evidence_notes") for value in result.evidence_notes],
        warnings=[clean(value, "worker warning") for value in result.warnings],
    )
    for field_name in dict.fromkeys(replaced_fields):
        warnings.append(f"Replaced angle-bracket placeholder in {field_name} with source-metadata unknown.")
    return cleaned


def _summary_field(value: object, key: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        text = _first_present_string(value, "text", "summary", "value", "answer")
        evidence = _evidence_refs(value)
        if not text:
            text = "unknown"
        if evidence and not _has_evidence(text):
            return f"{text} Evidence: {evidence}."
        return text
    return f"unknown (source: extraction metadata; {key} was not supported by the packet)"


def _evidence_refs(data: dict) -> str:
    value = data.get("evidence_refs") or data.get("evidence") or data.get("source")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        refs = [str(item).strip() for item in value if str(item).strip()]
        return "; ".join(refs)
    return ""


def validate_keyword_extraction(result: KeywordExtraction) -> None:
    for keyword in result.keywords:
        _validate_term(keyword.term, "keyword")
        _require_evidence(keyword.evidence, f"keyword {keyword.term}")
    for term in result.rag_terms:
        _validate_term(term.term, "rag term")
        if term.weight < 1 or term.weight > 5:
            raise KeywordQualityError(f"rag term weight must be 1-5: {term.term}")
        if term.role not in VALID_RAG_ROLES:
            raise KeywordQualityError(f"invalid rag term role for {term.term}: {term.role}")
        _require_evidence(term.evidence, f"rag term {term.term}")
    for label, line in (
        ("summary", result.summary),
        ("paper_role", result.paper_role),
        ("research_question", result.research_question),
        ("method_data_setting", result.method_data_setting),
        ("methods_or_basis", result.methods_or_basis),
    ):
        _require_evidence(line, label)
    for field_name, values in (
        ("key_claims", result.key_claims),
        ("idea_signals", result.idea_signals),
        ("connection_hooks", result.connection_hooks),
        ("evidence_notes", result.evidence_notes),
    ):
        for index, line in enumerate(values):
            _require_evidence(line, f"{field_name}[{index}]")
    for item in result.use_conditions:
        if item.category not in VALID_LIMITATION_CATEGORIES:
            raise KeywordQualityError(f"invalid limitation category: {item.category}")
        _require_evidence(item.evidence, f"use condition {item.category}")
    for item in result.improvement_directions:
        if item.category not in VALID_LIMITATION_CATEGORIES:
            raise KeywordQualityError(f"invalid improvement category: {item.category}")
        _require_evidence_or_rationale(item.evidence_or_rationale, f"improvement {item.category}")
    for signal in [*result.axon_signals, *result.dendrite_signals]:
        _require_evidence_or_rationale(signal.evidence, f"signal {signal.type}")


def run_openclaw_keyword_worker(
    packet: KeywordExtractionPacket,
    model: str,
    *,
    openclaw_bin: str = "openclaw",
    session_key: str | None = None,
    agent_id: str | None = None,
    channel: str = "last",
    timeout_seconds: int = 240,
    checkpoint_dir: Path | None = None,
) -> KeywordExtraction:
    if not shutil.which(openclaw_bin):
        raise KeywordWorkerError(f"OpenClaw binary not found: {openclaw_bin}")

    command = [openclaw_bin, "agent"]
    if agent_id:
        command.extend(["--agent", agent_id])
    command.extend(["--channel", channel])
    if session_key:
        command.extend(["--session-key", session_key])
    model_override = openclaw_model_override(model)
    if model_override:
        command.extend(["--model", model_override])
    command.extend(["--thinking", "minimal", "--json", "--message-file"])

    base_prompt = _prompt(packet)
    last_error, last_candidate, attempts, errors = _load_keyword_checkpoint(
        checkpoint_dir,
        packet,
    )
    if attempts >= MAX_KEYWORD_REPAIR_ATTEMPTS:
        raise KeywordValidationError(
            _validation_failure_summary(errors, last_error)
        )
    for attempt in range(attempts, MAX_KEYWORD_REPAIR_ATTEMPTS):
        prompt_text = (
            base_prompt
            if not last_candidate
            else _repair_prompt(last_error, last_candidate)
        )
        completed = _run_openclaw_agent(command, prompt_text, timeout_seconds)
        if completed.returncode != 0:
            error = completed.stderr.strip() or completed.stdout.strip()
            _save_keyword_checkpoint(
                checkpoint_dir,
                packet,
                attempt + 1,
                last_error or error,
                "",
                last_candidate,
                "runtime_failed",
                errors,
            )
            raise KeywordWorkerError(f"OpenClaw keyword worker failed: {error[-1000:]}")
        raw_output = _extract_text_from_openclaw_output(completed.stdout)
        candidate = last_candidate
        try:
            candidate = (
                raw_output
                if not last_candidate
                else _merge_candidate(last_candidate, raw_output)
            )
            result = parse_keyword_extraction(candidate, model=model)
            _save_keyword_checkpoint(
                checkpoint_dir,
                packet,
                attempt + 1,
                "",
                raw_output,
                candidate,
                "succeeded",
                errors,
            )
            return result
        except KeywordWorkerError as exc:
            last_error = str(exc)
            errors.append(last_error)
            last_candidate = candidate
            _save_keyword_checkpoint(
                checkpoint_dir,
                packet,
                attempt + 1,
                last_error,
                raw_output,
                last_candidate,
                "validation_failed",
                errors,
            )
    raise KeywordValidationError(
        _validation_failure_summary(errors, last_error)
    )


def _load_keyword_checkpoint(
    checkpoint_dir: Path | None,
    packet: KeywordExtractionPacket,
) -> tuple[str, str, int, list[str]]:
    if checkpoint_dir is None:
        return "", "", 0, []
    try:
        data = json.loads((checkpoint_dir / "manifest.json").read_text(encoding="utf-8"))
        if (
            data.get("contract_fingerprint") != KEYWORD_CONTRACT_FINGERPRINT
            or data.get("packet") != packet.to_payload()
            or data.get("status") not in {"validation_failed", "runtime_failed"}
        ):
            return "", "", 0, []
        attempts = int(data.get("attempts", 0))
        candidate_path = checkpoint_dir / str(data.get("candidate_output", ""))
        error = str(data.get("validation_error", "previous validation failed"))
        errors = [
            str(item)
            for item in data.get("validation_errors", [])
            if str(item).strip()
        ]
        if attempts >= MAX_KEYWORD_REPAIR_ATTEMPTS:
            return error, "", attempts, errors
        if not candidate_path.is_file():
            return "", "", 0, []
        return (
            error,
            candidate_path.read_text(encoding="utf-8"),
            attempts,
            errors,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return "", "", 0, []


def _save_keyword_checkpoint(
    checkpoint_dir: Path | None,
    packet: KeywordExtractionPacket,
    attempts: int,
    error: str,
    raw_output: str,
    candidate_output: str,
    status: str,
    errors: list[str],
) -> None:
    if checkpoint_dir is None:
        return
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    raw_name = f"raw-attempt-{attempts}.json"
    raw_path = checkpoint_dir / raw_name
    raw_path.write_text(raw_output, encoding="utf-8")
    candidate_name = f"candidate-attempt-{attempts}.json"
    candidate_path = checkpoint_dir / candidate_name
    candidate_path.write_text(candidate_output, encoding="utf-8")
    manifest = {
        "contract_fingerprint": KEYWORD_CONTRACT_FINGERPRINT,
        "packet": packet.to_payload(),
        "status": status,
        "attempts": attempts,
        "validation_error": error[-4000:],
        "validation_errors": [item[-4000:] for item in errors],
        "raw_output": raw_name,
        "candidate_output": candidate_name,
    }
    temporary = checkpoint_dir / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(checkpoint_dir / "manifest.json")


def _run_openclaw_agent(command: list[str], prompt_text: str, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as prompt:
        prompt.write(prompt_text)
        prompt_path = Path(prompt.name)
    try:
        try:
            return subprocess.run([*command, str(prompt_path)], text=True, capture_output=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise KeywordWorkerError(f"OpenClaw keyword worker timed out after {timeout_seconds}s") from exc
    finally:
        prompt_path.unlink(missing_ok=True)


def openclaw_model_override(model: str | None) -> str:
    """Return the CLI-safe OpenClaw model override for a host-owned selector."""
    selector = (model or "").strip()
    if not selector or selector.startswith("host:"):
        return ""
    return selector


def _repair_prompt(error: str, previous_output: str) -> str:
    """Ask the worker to repair its validated output, not re-normalize the source.

    The first attempt already contains the full extraction packet. Retrying with
    that packet causes the model to redo the whole normalization job and makes
    validation failures look like duplicate runs. The prior JSON is sufficient
    context for schema/evidence repairs; the worker must preserve valid fields.
    """
    return f"""You are repairing a ClawShelf normalization response.
Do not re-read or re-summarize the source. Return a JSON Merge Patch containing
only the field or fields required to fix the validation error. Do not repeat
unchanged fields. Arrays included in the patch replace the previous array.
Return exactly one JSON object, with no Markdown.

Validation error:
{error}

Previous response:
{previous_output}

Repair only the failed field(s). The host will merge this patch into the
previous response before validating the complete object.
"""


def _merge_candidate(previous_output: str, patch_output: str) -> str:
    try:
        previous = json.loads(_extract_json_object(previous_output))
        patch = json.loads(_extract_json_object(patch_output))
    except json.JSONDecodeError as exc:
        raise KeywordValidationError(
            f"repair patch is invalid JSON: {exc}"
        ) from exc
    if not isinstance(previous, dict):
        raise KeywordValidationError("previous candidate must be a JSON object")
    if not isinstance(patch, dict):
        raise KeywordValidationError("repair patch must be a JSON object")
    merged = _json_merge_patch(previous, patch)
    return json.dumps(merged, ensure_ascii=False)


def _json_merge_patch(target: object, patch: object) -> object:
    if not isinstance(patch, dict):
        return patch
    merged = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = _json_merge_patch(merged.get(key), value)
    return merged


def _validation_failure_summary(errors: list[str], last_error: str) -> str:
    history = [item for item in errors if item]
    if not history and last_error:
        history = [last_error]
    if not history:
        return "keyword validation failed after repair attempts"
    return (
        f"keyword validation failed after {len(history)} attempt(s); "
        f"first_error={history[0]}; last_error={history[-1]}"
    )


def _prompt(packet: KeywordExtractionPacket) -> str:
    return f"""You are the ClawShelf keyword and idea-signal extraction worker.
Return exactly one JSON object. Do not include Markdown.

Extract high-quality source-grounded fields for a normalized research record.
Read the section packets like a researcher reading a paper: identify the
problem, contribution, method/data/setting, findings, limitations/use
conditions, and transferable value. Reject author names, institutions, dates,
URLs, license boilerplate, LaTeX/PDF template text, OCR fragments, and generic
one-word terms. Cite packet evidence as `section: <heading_path>`; do not invent
page locations. Every factual field must include section/source evidence from
the packet. If evidence is missing, say source: extraction metadata or
rationale: <why>. Never emit angle-bracket placeholders. When a narrative
value is uncertain, write `unknown (source: extraction metadata)`.
Use the supplied shelf plan only to prioritize relevant terminology and idea
signals; never treat it as source evidence.

Required JSON keys:
title, summary, paper_role, research_question, method_data_setting, topics,
keywords, rag_terms, key_claims, methods_or_basis, use_conditions,
improvement_directions, axon_signals, dendrite_signals, idea_signals,
connection_hooks, evidence_notes, warnings, model.

summary: object with keys research_problem, core_contribution,
method_data_setting, key_findings, use_conditions_and_limits,
transferable_value. Every value is an object with text and evidence_refs.
paper_role: object with value and evidence. value describes the record's role
in the shelf; evidence is a `section: <heading_path>` reference.
research_question, method_data_setting, and methods_or_basis: evidence-bearing
strings that include a section/source citation.
topics, key_claims, idea_signals, connection_hooks, evidence_notes, warnings:
arrays that must always be present. Cover all six summary questions; use
unknown with source: extraction metadata when the packet does not support an
answer.
keywords: 8-15 objects with term, why, evidence.
rag_terms: 1-6 objects with term, weight 1-5, aliases array, evidence, role.
role must be one of topic, method, dataset, finding, limitation, idea_signal.
axon_signals must include types: Strong Contribution, Strong Method,
Strong Limitation, Strong Application Method.
dendrite_signals must include types: Assumption, Data / Domain Boundary,
Metric Choice, Failure Mode, Extension Hint.
use_conditions and improvement_directions category must be one of:
Scope Boundaries, Data / Evidence Limits, Method / Assumption Limits,
Evaluation Limits, Generalization Limits, Practical Use Limits,
Uncertainty / Conflicting Evidence, Extraction / Review Limits.
Every improvement_directions item must include category, direction,
expected_value, and evidence_or_rationale.
model must be a non-secret string label.

Packet:
{json.dumps(packet.to_payload(), ensure_ascii=False, indent=2)}
"""


def _keyword(item: object) -> KeywordSignal:
    data = _as_dict(item, "keyword")
    return KeywordSignal(
        term=_required_str(data, "term"),
        why=_required_str(data, "why"),
        evidence=_required_str(data, "evidence"),
    )


def _rag_term(item: object) -> RagSignal:
    data = _as_dict(item, "rag term")
    try:
        weight = int(data.get("weight", 0))
    except (TypeError, ValueError) as exc:
        raise KeywordWorkerError("rag term weight must be an integer") from exc
    aliases = data.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [part.strip() for part in aliases.split(";") if part.strip() and part.strip().lower() != "none"]
    if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
        raise KeywordWorkerError("rag term aliases must be a list of strings")
    return RagSignal(
        term=_required_str(data, "term"),
        weight=weight,
        aliases=[alias.strip() for alias in aliases if alias.strip()],
        evidence=_required_str(data, "evidence"),
        role=_required_str(data, "role"),
    )


def _signal(item: object, valid_types: set[str], field_name: str) -> StructuredSignal:
    data = _as_dict(item, field_name)
    signal_type = _required_str(data, "type")
    if signal_type not in valid_types:
        raise KeywordQualityError(f"{field_name} invalid type: {signal_type}")
    return StructuredSignal(
        type=signal_type,
        signal=_required_str_with_fallback(data, "signal", "text", "description"),
        evidence=_required_str_with_fallback(data, "evidence", "source", "rationale", "evidence_or_rationale"),
    )


def _use_condition(item: object) -> LimitationUseCondition:
    data = _as_dict(item, "use condition")
    return LimitationUseCondition(
        category=_required_str(data, "category"),
        limitation=_required_str_with_fallback(data, "limitation", "condition", "text", "description"),
        implication=_required_str_with_fallback(
            data,
            "implication",
            "implications",
            "impact",
            "use_condition",
            "limitation",
            "condition",
            "text",
            "description",
        ),
        evidence=_required_str_with_fallback(data, "evidence", "source", "rationale", "evidence_or_rationale"),
    )


def _improvement(item: object) -> LimitationImprovement:
    data = _as_dict(item, "improvement direction")
    return LimitationImprovement(
        category=_required_str(data, "category"),
        direction=_required_str_with_fallback(data, "direction", "improvement", "text", "description"),
        expected_value=_required_str_with_fallback(
            data,
            "expected_value",
            "value",
            "benefit",
            "impact",
            "direction",
            "improvement",
            "text",
            "description",
        ),
        evidence_or_rationale=_required_str_with_fallback(data, "evidence_or_rationale", "evidence", "source", "rationale"),
    )


def _object_list(data: dict, key: str, minimum: int, maximum: int | None = None) -> list[object]:
    value = data.get(key)
    if not isinstance(value, list):
        raise KeywordWorkerError(f"{key} must be a list")
    if len(value) < minimum:
        raise KeywordWorkerError(f"{key} must contain at least {minimum} entries")
    if maximum is not None and len(value) > maximum:
        raise KeywordWorkerError(f"{key} must contain at most {maximum} entries")
    return value


def _string_list(data: dict, key: str, minimum: int) -> list[str]:
    value = data.get(key, [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise KeywordWorkerError(f"{key} must be a list of strings")
    stripped = [_string_item(item, key) for item in value]
    stripped = [item for item in stripped if item]
    if len(stripped) < minimum:
        raise KeywordWorkerError(f"{key} must contain at least {minimum} entries")
    return stripped


def _string_item(item: object, field_name: str) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        raise KeywordWorkerError(f"{field_name} must be a list of strings")
    text = _first_present_string(
        item,
        "text",
        "claim",
        "signal",
        "idea",
        "connection",
        "hook",
        "note",
        "message",
        "warning",
        "direction",
        "summary",
        "value",
        "term",
    )
    evidence = _first_present_string(item, "evidence", "source", "evidence_or_rationale", "rationale")
    if not text:
        raise KeywordWorkerError(f"{field_name} item must contain text")
    if evidence and evidence.lower() not in text.lower():
        return f"{text} (evidence: {evidence})"
    return text


def _first_present_string(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_dict(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise KeywordWorkerError(f"{label} must be an object")
    return value


def _required_str(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KeywordWorkerError(f"{key} must be a non-empty string")
    return value.strip()


def _required_str_with_fallback(data: dict, key: str, *fallback_keys: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    for fallback_key in fallback_keys:
        fallback = data.get(fallback_key)
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip()
    raise KeywordWorkerError(f"{key} must be a non-empty string")


def _validate_term(value: str, label: str) -> None:
    normalized = re.sub(r"\s+", " ", value.lower()).strip()
    if PLACEHOLDER_RE.search(value):
        raise KeywordQualityError(f"{label} contains a placeholder")
    if BAD_TERM_RE.search(normalized) or OCR_FRAGMENT_RE.search(normalized):
        raise KeywordQualityError(f"{label} contains boilerplate or OCR noise: {value}")
    if len(normalized.split()) == 1 and len(normalized) < 4:
        raise KeywordQualityError(f"{label} is too generic or short: {value}")


def _require_evidence(value: str, label: str) -> None:
    if not _has_evidence(value):
        raise KeywordQualityError(f"{label} has no evidence")


def _has_evidence(value: str) -> bool:
    return bool(re.search(r"\b(source|page|pages|section|sheet|url|paragraph|evidence)\b|pp?\.|[\u4e00-\u9fff]*(证据|来源|页|章节|表格)", value, re.IGNORECASE))


def _require_evidence_or_rationale(value: str, label: str) -> None:
    if re.search(r"\b(rationale|because|inferred|推断|理由)\b", value, re.IGNORECASE):
        return
    _require_evidence(value, label)


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise KeywordWorkerError("keyword worker returned no JSON object")
    return stripped[start : end + 1]


def _extract_text_from_openclaw_output(stdout: str) -> str:
    stripped = stdout.strip()
    if not stripped:
        raise KeywordWorkerError("OpenClaw keyword worker returned empty output")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(payload, str):
        return payload
    extracted = _find_text(payload)
    return extracted or stripped


def _find_text(value: object) -> str:
    if isinstance(value, dict):
        for key in ("final", "text", "message", "output", "content", "response"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item
        for item in value.values():
            found = _find_text(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_text(item)
            if found:
                return found
    return ""
