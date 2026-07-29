from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from .idea import IdeaCandidate, generate_idea_candidates
from .normalize import NormalizedRecord, RagTerm, SignalEntry
from .semantic_retrieval import SemanticRetrievalResult
from .terms import TermMatch, match_rag_terms, normalize_term, shared_bridge_concepts


class CreativityScoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScoreBreakdown:
    relationship: int
    evidence: int
    novelty_or_tension: int
    actionability: int
    risk: int

    @property
    def total(self) -> int:
        return (
            self.relationship
            + self.evidence
            + self.novelty_or_tension
            + self.actionability
            - self.risk
        )


@dataclass(frozen=True)
class MatchedEvidence:
    signal: str
    new_evidence: str
    linked_evidence: str
    why_it_matters: str


@dataclass(frozen=True)
class CreativityCandidate:
    linked_record_path: str
    linked_record: NormalizedRecord
    retrieval_path: list[str]
    matched_terms: list[TermMatch] = field(default_factory=list)
    bridge_concepts: list[str] = field(default_factory=list)
    bridge_evidence: list[MatchedEvidence] = field(default_factory=list)
    idea_candidates: list[IdeaCandidate] = field(default_factory=list)
    semantic_similarity: float | None = None


@dataclass(frozen=True)
class CreativityScoreResult:
    breakdown: ScoreBreakdown
    confidence: float
    matched_evidence: list[MatchedEvidence] = field(default_factory=list)
    verdict: str = "p2_intake"
    method: str = "deterministic"
    model: str = ""

    @property
    def creativity_score(self) -> int:
        return self.breakdown.total


@dataclass(frozen=True)
class EvidencePacket:
    source: str
    title: str
    summary: str
    keywords: list[str]
    rag_terms: list[dict]
    key_claims: str
    methods_or_basis: str
    limitations: str
    improvement_directions: str
    axon_signals: list[dict]
    dendrite_signals: list[dict]
    idea_signals: str
    connection_hooks: str


@dataclass(frozen=True)
class CreativityScoreCandidate:
    linked_record_path: str
    linked_record: EvidencePacket
    retrieval_path: list[str]
    bridge_concepts: list[str]
    semantic_similarity: float | None = None


@dataclass(frozen=True)
class CreativityScoreRequest:
    new_record_path: str
    new_record: EvidencePacket
    candidates: list[CreativityScoreCandidate]
    shelf_plan: dict[str, str] = field(default_factory=dict)
    novelty_preference: float = 0.5


class CreativityRunner(Protocol):
    def __call__(
        self,
        request: CreativityScoreRequest,
        model: str,
    ) -> dict[str, CreativityScoreResult]:
        ...


def retrieve_candidates(
    new_record: NormalizedRecord,
    records: list[tuple[Path, NormalizedRecord]],
    *,
    candidate_limit: int,
    novelty_preference: float,
) -> list[CreativityCandidate]:
    candidates: list[CreativityCandidate] = []
    new_terms = _record_rag_terms(new_record)
    new_values = _record_values(new_record)
    for path, linked_record in records:
        matched_terms = match_rag_terms(new_terms, _record_rag_terms(linked_record))
        bridges = shared_bridge_concepts(new_values, _record_values(linked_record))
        bridge_evidence = _bridge_evidence(new_record, linked_record, bridges)
        ideas = generate_idea_candidates(
            new_record,
            linked_record,
            novelty_preference=novelty_preference,
        )
        if not matched_terms and not bridge_evidence and not ideas:
            continue
        retrieval_path: list[str] = []
        if matched_terms:
            retrieval_path.append("rag_exact_or_alias")
        if bridge_evidence:
            retrieval_path.append("structured_concept_bridge")
        if ideas:
            retrieval_path.append("structured_relation_candidate")
        candidates.append(
            CreativityCandidate(
                linked_record_path=str(path),
                linked_record=linked_record,
                retrieval_path=retrieval_path,
                matched_terms=matched_terms[:12],
                bridge_concepts=[item.signal for item in bridge_evidence[:12]],
                bridge_evidence=bridge_evidence[:8],
                idea_candidates=ideas,
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: _candidate_priority(candidate, novelty_preference),
        reverse=True,
    )[:candidate_limit]


def merge_semantic_candidates(
    candidates: list[CreativityCandidate],
    result: SemanticRetrievalResult,
    records: list[tuple[Path, NormalizedRecord]],
    *,
    candidate_limit: int,
    novelty_preference: float,
) -> list[CreativityCandidate]:
    """Append QMD hits without treating vector similarity as a creativity score."""
    by_path = {str(path.resolve()): record for path, record in records}
    merged = list(candidates)
    positions = {
        str(Path(candidate.linked_record_path).resolve()): index
        for index, candidate in enumerate(merged)
    }
    for hit in result.hits:
        resolved = str(Path(hit.path).resolve())
        linked_record = by_path.get(resolved)
        if linked_record is None:
            continue
        existing_index = positions.get(resolved)
        if existing_index is not None:
            existing = merged[existing_index]
            retrieval_path = list(existing.retrieval_path)
            if "qmd_vector" not in retrieval_path:
                retrieval_path.append("qmd_vector")
            merged[existing_index] = CreativityCandidate(
                linked_record_path=existing.linked_record_path,
                linked_record=existing.linked_record,
                retrieval_path=retrieval_path,
                matched_terms=existing.matched_terms,
                bridge_concepts=existing.bridge_concepts,
                bridge_evidence=existing.bridge_evidence,
                idea_candidates=existing.idea_candidates,
                semantic_similarity=hit.similarity,
            )
            continue
        if len(merged) >= candidate_limit:
            break
        semantic_candidate = CreativityCandidate(
            linked_record_path=resolved,
            linked_record=linked_record,
            retrieval_path=["qmd_vector"],
            semantic_similarity=hit.similarity,
        )
        positions[resolved] = len(merged)
        merged.append(semantic_candidate)
    return merged[:candidate_limit]


def deterministic_score(candidate: CreativityCandidate) -> CreativityScoreResult:
    exact_count = len(candidate.matched_terms)
    bridge_count = len(candidate.bridge_evidence)
    top_idea = candidate.idea_candidates[0] if candidate.idea_candidates else None
    if exact_count:
        relationship = 5
    elif top_idea and top_idea.idea_type == "innovation":
        relationship = 5
    elif top_idea and top_idea.idea_type == "consolidation":
        relationship = 4
    elif bridge_count >= 2:
        relationship = 4
    else:
        relationship = 3

    evidence_count = sum(
        bool(item.new_evidence and item.linked_evidence)
        for item in _candidate_evidence(candidate)
    )
    evidence = 5 if evidence_count else 0
    novelty = min(5, top_idea.novelty_score) if top_idea else 2 if bridge_count else 1
    actionability = min(5, top_idea.feasibility_score) if top_idea else 2
    risk = 0 if evidence_count else 3
    if exact_count and evidence_count:
        confidence = 0.8
    elif top_idea and evidence_count:
        confidence = 0.75
    elif bridge_count and evidence_count:
        confidence = 0.7
    else:
        confidence = 0.4
    breakdown = ScoreBreakdown(relationship, evidence, novelty, actionability, risk)
    matched_evidence = _candidate_evidence(candidate)
    verdict = (
        "p1_candidate"
        if breakdown.total >= 13 and confidence >= 0.65 and _has_bidirectional_evidence(matched_evidence)
        else "p2_intake"
    )
    return CreativityScoreResult(
        breakdown=breakdown,
        confidence=confidence,
        matched_evidence=matched_evidence,
        verdict=verdict,
        method="deterministic",
    )


def is_p1(
    result: CreativityScoreResult,
    *,
    threshold: int,
    min_confidence: float,
) -> bool:
    return (
        result.creativity_score >= threshold
        and result.confidence >= min_confidence
        and result.verdict == "p1_candidate"
        and _has_bidirectional_evidence(result.matched_evidence)
    )


def ground_host_result(
    result: CreativityScoreResult,
    new_record: NormalizedRecord,
    linked_record: NormalizedRecord,
) -> CreativityScoreResult:
    """Discard host evidence that cannot be traced to both normalized records."""
    new_corpus = _evidence_corpus(new_record)
    linked_corpus = _evidence_corpus(linked_record)
    grounded = [
        item
        for item in result.matched_evidence
        if _evidence_is_grounded(item.new_evidence, new_corpus)
        and _evidence_is_grounded(item.linked_evidence, linked_corpus)
    ]
    verdict = result.verdict
    if verdict == "p1_candidate" and not _has_bidirectional_evidence(grounded):
        verdict = "p2_intake"
    return CreativityScoreResult(
        breakdown=result.breakdown,
        confidence=result.confidence,
        matched_evidence=grounded,
        verdict=verdict,
        method=result.method,
        model=result.model,
    )


def evidence_packet(record: NormalizedRecord) -> EvidencePacket:
    return EvidencePacket(
        source=record.frontmatter.get("source", ""),
        title=record.title,
        summary=record.sections.get("Summary", ""),
        keywords=[keyword.raw for keyword in record.keywords[:12]],
        rag_terms=[_rag_term_payload(term) for term in record.rag_terms[:12]],
        key_claims=record.sections.get("Key Claims", ""),
        methods_or_basis=record.sections.get("Methods or Basis", ""),
        limitations=record.sections.get("Limitations", ""),
        improvement_directions=_improvement_directions(record),
        axon_signals=[_signal_payload(signal) for signal in record.axon_signals],
        dendrite_signals=[_signal_payload(signal) for signal in record.dendrite_signals],
        idea_signals=record.sections.get("Idea Signals", ""),
        connection_hooks=record.sections.get("Connection Hooks", ""),
    )


def parse_creativity_score(text: str, model: str = "") -> CreativityScoreResult:
    payload = _extract_json_object(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CreativityScoreError(f"invalid creativity scorer JSON: {exc}") from exc
    return _parse_one_score(data, model)


def parse_creativity_scores(text: str, model: str = "") -> dict[str, CreativityScoreResult]:
    payload = _extract_json_object(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CreativityScoreError(f"invalid creativity scorer JSON: {exc}") from exc
    scores = data.get("scores")
    if not isinstance(scores, list):
        raise CreativityScoreError("scores must be a list")
    parsed: dict[str, CreativityScoreResult] = {}
    for item in scores:
        if not isinstance(item, dict):
            raise CreativityScoreError("score must be an object")
        path = str(item.get("linked_record_path", "")).strip()
        if not path:
            raise CreativityScoreError("score missing linked_record_path")
        parsed[path] = _parse_one_score(item, model)
    return parsed


def run_openclaw_creativity_scorer(
    request: CreativityScoreRequest,
    model: str,
    *,
    openclaw_bin: str = "openclaw",
    session_key: str | None = None,
    agent_id: str | None = None,
    channel: str = "last",
    timeout_seconds: int = 180,
) -> dict[str, CreativityScoreResult]:
    if not shutil.which(openclaw_bin):
        raise CreativityScoreError(f"OpenClaw binary not found: {openclaw_bin}")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as prompt:
        prompt.write(_prompt(request))
        prompt_path = Path(prompt.name)
    command = [openclaw_bin, "agent"]
    if agent_id:
        command.extend(["--agent", agent_id])
    command.extend(["--channel", channel])
    if session_key:
        command.extend(["--session-key", session_key])
    model_override = openclaw_model_override(model)
    if model_override:
        command.extend(["--model", model_override])
    command.extend(["--thinking", "minimal", "--json", "--message-file", str(prompt_path)])
    try:
        try:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise CreativityScoreError(
                f"OpenClaw creativity scorer timed out after {timeout_seconds}s"
            ) from exc
    finally:
        prompt_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip()
        raise CreativityScoreError(f"OpenClaw creativity scorer failed: {error[-1000:]}")
    return parse_creativity_scores(_extract_text_from_openclaw_output(completed.stdout), model=model)


def openclaw_model_override(model: str | None) -> str:
    selector = (model or "").strip()
    if not selector or selector.startswith("host:"):
        return ""
    return selector


def _parse_one_score(data: dict, model: str = "") -> CreativityScoreResult:
    evidence = data.get("matched_evidence", [])
    if not isinstance(evidence, list):
        raise CreativityScoreError("matched_evidence must be a list")
    breakdown = ScoreBreakdown(
        relationship=_score_int(data, "relationship"),
        evidence=_score_int(data, "evidence"),
        novelty_or_tension=_score_int(data, "novelty_or_tension"),
        actionability=_score_int(data, "actionability"),
        risk=_score_int(data, "risk", maximum=3),
    )
    result = CreativityScoreResult(
        breakdown=breakdown,
        confidence=_confidence(data),
        matched_evidence=[_matched_evidence(item) for item in evidence],
        verdict=str(data.get("verdict", "p2_intake")).strip(),
        method="host",
        model=str(data.get("model") or model or ""),
    )
    if result.verdict not in {"p1_candidate", "p2_intake"}:
        raise CreativityScoreError(f"invalid verdict: {result.verdict}")
    return result


def _record_rag_terms(record: NormalizedRecord) -> list[RagTerm]:
    if record.rag_terms:
        return record.rag_terms
    return [
        RagTerm(keyword.term, 3, [], keyword.evidence, "topic")
        for keyword in record.keywords
    ]


def _record_values(record: NormalizedRecord) -> list[str]:
    return [
        record.title,
        *[term.term for term in record.rag_terms],
        *[alias for term in record.rag_terms for alias in term.aliases],
        *[keyword.term for keyword in record.keywords],
        *[signal.signal for signal in [*record.axon_signals, *record.dendrite_signals]],
        record.sections.get("Methods or Basis", ""),
        record.sections.get("Limitations", ""),
        record.sections.get("Idea Signals", ""),
        record.sections.get("Connection Hooks", ""),
    ]


def _evidence_entries(record: NormalizedRecord) -> list[tuple[str, str]]:
    entries = [
        (term.term, term.evidence)
        for term in record.rag_terms
        if term.term and term.evidence
    ]
    entries.extend(
        (signal.signal, signal.evidence)
        for signal in [*record.axon_signals, *record.dendrite_signals]
        if signal.signal and signal.evidence
    )
    return entries


def _bridge_evidence(
    new_record: NormalizedRecord,
    linked_record: NormalizedRecord,
    concepts: list[str],
) -> list[MatchedEvidence]:
    matches: list[MatchedEvidence] = []
    for concept in concepts:
        normalized = normalize_term(concept)
        new_entry = next(
            (
                (signal, evidence)
                for signal, evidence in _evidence_entries(new_record)
                if normalized in normalize_term(signal)
            ),
            None,
        )
        linked_entry = next(
            (
                (signal, evidence)
                for signal, evidence in _evidence_entries(linked_record)
                if normalized in normalize_term(signal)
            ),
            None,
        )
        if not new_entry or not linked_entry:
            continue
        matches.append(
            MatchedEvidence(
                signal=concept,
                new_evidence=new_entry[1],
                linked_evidence=linked_entry[1],
                why_it_matters=f"structured concept bridge: {concept}",
            )
        )
    return matches


def _candidate_evidence(candidate: CreativityCandidate) -> list[MatchedEvidence]:
    evidence = list(candidate.bridge_evidence)
    seen = {(item.signal, item.new_evidence, item.linked_evidence) for item in evidence}
    for match in candidate.matched_terms:
        item = MatchedEvidence(
            signal=match.term,
            new_evidence=match.evidence,
            linked_evidence=match.linked_evidence,
            why_it_matters=f"evidence-backed RAG {match.role} match",
        )
        key = (item.signal, item.new_evidence, item.linked_evidence)
        if key not in seen:
            seen.add(key)
            evidence.append(item)
    for idea in candidate.idea_candidates:
        item = MatchedEvidence(
            signal=f"{idea.new_signal} ↔ {idea.linked_signal}",
            new_evidence=idea.new_evidence,
            linked_evidence=idea.linked_evidence,
            why_it_matters=(
                f"evidence-backed {idea.idea_type} relation: "
                f"{idea.new_signal_type} → {idea.linked_signal_type}"
            ),
        )
        key = (item.signal, item.new_evidence, item.linked_evidence)
        if key not in seen:
            seen.add(key)
            evidence.append(item)
    return evidence[:8]


def _candidate_priority(candidate: CreativityCandidate, novelty_preference: float) -> float:
    exact = sum(match.score for match in candidate.matched_terms[:3])
    bridge = len(candidate.bridge_evidence) * 4
    if candidate.idea_candidates:
        idea = candidate.idea_candidates[0]
        overlap = idea.overlap_score + idea.evidence_score + idea.feasibility_score
        novelty = idea.novelty_score + idea.complementarity_score
        idea_priority = (1 - novelty_preference) * overlap + novelty_preference * novelty
    else:
        idea_priority = 0
    return exact + bridge + idea_priority


def _has_bidirectional_evidence(evidence: list[MatchedEvidence]) -> bool:
    return any(item.new_evidence and item.linked_evidence for item in evidence)


def _evidence_corpus(record: NormalizedRecord) -> str:
    values = [
        record.title,
        *record.sections.values(),
        *[term.evidence for term in record.rag_terms],
        *[
            signal.evidence
            for signal in [*record.axon_signals, *record.dendrite_signals]
        ],
    ]
    return normalize_term(" ".join(value for value in values if value))


def _evidence_is_grounded(value: str, corpus: str) -> bool:
    evidence = normalize_term(value)
    return bool(evidence and corpus and evidence in corpus)


def _improvement_directions(record: NormalizedRecord) -> str:
    limitations = record.sections.get("Limitations", "")
    marker = "### Improvement Directions"
    chinese_marker = "### 改进方向"
    if marker in limitations:
        return limitations.split(marker, 1)[1].strip()
    if chinese_marker in limitations:
        return limitations.split(chinese_marker, 1)[1].strip()
    return ""


def _rag_term_payload(term: RagTerm) -> dict:
    return asdict(term)


def _signal_payload(signal: SignalEntry) -> dict:
    return {
        "type": signal.type,
        "signal": signal.signal,
        "evidence": signal.evidence,
    }


def _score_int(data: dict, key: str, maximum: int = 5) -> int:
    try:
        value = int(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise CreativityScoreError(f"{key} must be an integer") from exc
    if value < 0 or value > maximum:
        raise CreativityScoreError(f"{key} must be 0-{maximum}")
    return value


def _confidence(data: dict) -> float:
    try:
        value = float(data["confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CreativityScoreError("confidence must be a number") from exc
    if value < 0 or value > 1:
        raise CreativityScoreError("confidence must be 0-1")
    return value


def _matched_evidence(item: object) -> MatchedEvidence:
    if not isinstance(item, dict):
        raise CreativityScoreError("matched evidence must be an object")
    return MatchedEvidence(
        signal=str(item.get("signal", "")).strip(),
        new_evidence=str(item.get("new_evidence", "")).strip(),
        linked_evidence=str(item.get("linked_evidence", "")).strip(),
        why_it_matters=str(item.get("why_it_matters", "")).strip(),
    )


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise CreativityScoreError("creativity scorer returned no JSON object")
    return stripped[start : end + 1]


def _extract_text_from_openclaw_output(stdout: str) -> str:
    stripped = stdout.strip()
    if not stripped:
        raise CreativityScoreError("OpenClaw creativity scorer returned empty output")
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


def _prompt(request: CreativityScoreRequest) -> str:
    payload = json.dumps(asdict(request), ensure_ascii=False, indent=2)
    return (
        "Score source-backed creative research relationships. Use only the supplied "
        "normalized evidence. Return exactly one JSON object with a scores array. "
        "Each score must include linked_record_path, relationship, evidence, "
        "novelty_or_tension, actionability, risk, confidence, matched_evidence, "
        "verdict, and model. Component values are 0-5 except risk 0-3 and confidence "
        "0-1. verdict must be p1_candidate or p2_intake. A p1_candidate requires "
        "specific evidence from both records; shared domain words alone are insufficient.\n\n"
        "<request>\n"
        f"{payload}\n"
        "</request>\n"
    )
