from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import product

from .normalize import NormalizedRecord, SignalEntry
from .terms import is_generic_term, normalize_term


INNOVATION_THRESHOLD = 12
CONSOLIDATION_THRESHOLD = 13

COMPLEMENTARY_PAIRS = {
    ("Strong Contribution", "Strong Limitation"),
    ("Strong Contribution", "Failure Mode"),
    ("Strong Method", "Strong Limitation"),
    ("Strong Method", "Extension Hint"),
    ("Strong Application Method", "Data / Domain Boundary"),
    ("Strong Application Method", "Extension Hint"),
}
CONSOLIDATION_PAIRS = {
    ("Strong Method", "Metric Choice"),
    ("Strong Limitation", "Data / Domain Boundary"),
    ("Strong Limitation", "Failure Mode"),
    ("Assumption", "Data / Domain Boundary"),
}


@dataclass(frozen=True)
class IdeaCandidate:
    idea_type: str
    new_signal_type: str
    linked_signal_type: str
    new_signal: str
    linked_signal: str
    new_evidence: str
    linked_evidence: str
    overlap_score: int
    complementarity_score: int
    novelty_score: int
    evidence_score: int
    feasibility_score: int

    @property
    def total_score(self) -> int:
        return (
            self.overlap_score
            + self.complementarity_score
            + self.novelty_score
            + self.evidence_score
            + self.feasibility_score
        )


def generate_idea_candidates(
    new_record: NormalizedRecord,
    linked_record: NormalizedRecord,
    limit: int = 5,
    novelty_preference: float = 0.5,
) -> list[IdeaCandidate]:
    candidates: list[IdeaCandidate] = []
    for candidate in generate_relation_candidates(new_record, linked_record):
        if candidate.idea_type != "reject":
            candidates.append(candidate)
        elif (
            candidate.overlap_score >= 1
            and candidate.complementarity_score >= 3
            and candidate.evidence_score >= 4
        ):
            candidates.append(replace(candidate, idea_type="relation_candidate"))
    def priority(item: IdeaCandidate) -> float:
        overlap = item.overlap_score + item.evidence_score + item.feasibility_score
        novelty = item.novelty_score + item.complementarity_score
        return (1 - novelty_preference) * overlap + novelty_preference * novelty

    return sorted(candidates, key=lambda item: (priority(item), item.total_score), reverse=True)[:limit]


def generate_relation_candidates(
    new_record: NormalizedRecord,
    linked_record: NormalizedRecord,
) -> list[IdeaCandidate]:
    """Generate evidence-bearing signal pairs without requiring a RAG-term match."""
    candidates: list[IdeaCandidate] = []
    for new_signal, linked_signal in product(_signals(new_record), _signals(linked_record)):
        if not new_signal.evidence or not linked_signal.evidence:
            continue
        candidates.append(score_signal_pair(new_signal, linked_signal))
    return sorted(candidates, key=lambda item: item.total_score, reverse=True)


def score_signal_pair(new_signal: SignalEntry, linked_signal: SignalEntry) -> IdeaCandidate:
    return score_signal_pair_with_terms(
        new_signal,
        linked_signal,
        content_terms(new_signal.signal),
        content_terms(linked_signal.signal),
    )


def score_signal_pair_with_terms(
    new_signal: SignalEntry,
    linked_signal: SignalEntry,
    new_terms: frozenset[str],
    linked_terms: frozenset[str],
) -> IdeaCandidate:
    """Score a signal pair with pre-computed content terms.

    Callers that compare every signal against every other signal (the overview
    synapse pass) normalize each signal once and reuse the term sets, which is
    an order of magnitude cheaper than re-normalizing inside every comparison.
    """
    overlap = overlap_from_terms(new_terms, linked_terms)
    complementarity = _complementarity_score(new_signal.type, linked_signal.type)
    novelty = _novelty_score(overlap, complementarity)
    evidence = _evidence_score(new_signal.evidence, linked_signal.evidence)
    feasibility = _feasibility_score(new_signal, linked_signal)
    idea_type = _classify(new_signal.type, linked_signal.type, overlap, complementarity, novelty, evidence)
    return IdeaCandidate(
        idea_type=idea_type,
        new_signal_type=new_signal.type,
        linked_signal_type=linked_signal.type,
        new_signal=new_signal.signal,
        linked_signal=linked_signal.signal,
        new_evidence=new_signal.evidence,
        linked_evidence=linked_signal.evidence,
        overlap_score=overlap,
        complementarity_score=complementarity,
        novelty_score=novelty,
        evidence_score=evidence,
        feasibility_score=feasibility,
    )


def _signals(record: NormalizedRecord) -> list[SignalEntry]:
    return [*record.axon_signals, *record.dendrite_signals]


def _overlap_score(left: str, right: str) -> int:
    return overlap_from_terms(content_terms(left), content_terms(right))


def overlap_from_terms(
    left_terms: frozenset[str],
    right_terms: frozenset[str],
) -> int:
    if not left_terms or not right_terms:
        return 0
    shared = left_terms & right_terms
    if not shared:
        return 1 if _nearby_terms(left_terms, right_terms) else 0
    ratio = len(shared) / min(len(left_terms), len(right_terms))
    if ratio >= 0.8:
        return 5
    if ratio >= 0.45:
        return 4
    if ratio >= 0.2:
        return 3
    return 2


def _complementarity_score(left_type: str, right_type: str) -> int:
    if (left_type, right_type) in COMPLEMENTARY_PAIRS or (right_type, left_type) in COMPLEMENTARY_PAIRS:
        return 5
    if (left_type, right_type) in CONSOLIDATION_PAIRS or (right_type, left_type) in CONSOLIDATION_PAIRS:
        return 3
    if left_type == right_type:
        return 2
    return 1


def _novelty_score(overlap: int, complementarity: int) -> int:
    if overlap in {2, 3, 4} and complementarity >= 4:
        return 4
    if overlap >= 4 and complementarity >= 2:
        return 2
    if overlap <= 1 and complementarity >= 4:
        return 1
    return 0


def _evidence_score(left_evidence: str, right_evidence: str) -> int:
    score = 0
    for evidence in (left_evidence, right_evidence):
        lowered = evidence.lower()
        if any(marker in lowered for marker in ("p.", "pp.", "page", "section", "source", "rationale", "证据", "来源")):
            score += 2
    return score


def _feasibility_score(left: SignalEntry, right: SignalEntry) -> int:
    if not left.signal or not right.signal:
        return 0
    if left.type in {"Strong Method", "Strong Application Method"} or right.type in {"Strong Method", "Strong Application Method"}:
        return 3
    return 2


def _classify(
    left_type: str,
    right_type: str,
    overlap: int,
    complementarity: int,
    novelty: int,
    evidence: int,
) -> str:
    score = overlap + complementarity + novelty + evidence
    if score >= INNOVATION_THRESHOLD and 2 <= overlap <= 4 and complementarity >= 4 and novelty >= 3:
        return "innovation"
    if score >= CONSOLIDATION_THRESHOLD and overlap >= 4 and complementarity >= 2 and left_type != right_type:
        return "consolidation"
    return "reject"


@lru_cache(maxsize=4096)
def content_terms(value: str) -> frozenset[str]:
    normalized = normalize_term(value)
    parts = [part for part in normalized.split() if not is_generic_term(part)]
    terms = {part for part in parts if len(part) >= 3}
    for width in (3, 2):
        for index in range(0, max(0, len(parts) - width + 1)):
            phrase = " ".join(parts[index : index + width])
            if not is_generic_term(phrase):
                terms.add(phrase)
    return frozenset(terms)


def _nearby_terms(left_terms: set[str], right_terms: set[str]) -> bool:
    for left in left_terms:
        for right in right_terms:
            if left in right or right in left:
                return True
    return False
