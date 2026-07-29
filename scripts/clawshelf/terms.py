from __future__ import annotations

from dataclasses import dataclass
import re

from .normalize import NormalizedRecord, RagTerm


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}
GENERIC_TERMS = {
    "about",
    "abstract",
    "against",
    "agent",
    "algorithm",
    "analysis",
    "article",
    "data",
    "evidence",
    "finding",
    "market",
    "method",
    "paper",
    "result",
    "results",
    "research",
    "study",
    "category",
    "section",
    "source",
    "scope",
    "trading",
    "模型",
    "方法",
    "结果",
    "市场",
    "研究",
    "论文",
}
ROLE_BONUS = {
    "finding": 4,
    "method": 3,
    "dataset": 3,
    "topic": 2,
    "limitation": 2,
    "idea_signal": 2,
}
TERM_RE = re.compile(r"[^\w\s\u4e00-\u9fff-]+")
HYPHEN_RE = re.compile(r"[-‐‑‒–—―]+")


@dataclass(frozen=True)
class TermMatch:
    term: str
    role: str
    evidence: str
    linked_evidence: str
    score: int


def normalize_term(value: str) -> str:
    cleaned = HYPHEN_RE.sub(" ", value.lower())
    cleaned = TERM_RE.sub(" ", cleaned)
    parts = [_canonical_token(part) for part in cleaned.split()]
    return " ".join(part for part in parts if part).strip(" _")


def semantic_query_text(record: NormalizedRecord, max_characters: int = 6000) -> str:
    values = [
        record.title,
        record.sections.get("Research Question", ""),
        record.sections.get("Key Claims", ""),
        " ".join(term.term for term in record.rag_terms),
        " ".join(signal.signal for signal in record.axon_signals),
        " ".join(signal.signal for signal in record.dendrite_signals),
    ]
    query = "\n".join(value.strip() for value in values if value and value.strip())
    return query[:max_characters]


def _canonical_token(value: str) -> str:
    if (
        len(value) > 4
        and value.endswith("s")
        and not value.endswith(("ss", "is", "us"))
    ):
        return value[:-1]
    return value


def term_variants(term: RagTerm) -> set[str]:
    variants = {normalize_term(term.term)}
    variants.update(normalize_term(alias) for alias in term.aliases)
    return {variant for variant in variants if variant}


def is_generic_term(value: str) -> bool:
    normalized = normalize_term(value)
    if not normalized:
        return True
    parts = normalized.split()
    if len(parts) == 1:
        return normalized in STOPWORDS or normalized in GENERIC_TERMS or len(normalized) < 3
    useful_parts = [part for part in parts if part not in STOPWORDS and part not in GENERIC_TERMS]
    return len(useful_parts) == 0


def bridge_concepts(values: list[str]) -> set[str]:
    """Extract conservative multi-word concepts for candidate retrieval only."""
    concepts: set[str] = set()
    for value in values:
        parts = normalize_term(value).split()
        if not parts:
            continue
        for width in (3, 2):
            for index in range(0, len(parts) - width + 1):
                phrase_parts = parts[index : index + width]
                useful = [
                    part
                    for part in phrase_parts
                    if part not in STOPWORDS and part not in GENERIC_TERMS and len(part) >= 3
                ]
                contains_stopword = any(part in STOPWORDS for part in phrase_parts)
                meaningful_domain_phrase = (
                    len(useful) >= 1
                    and len(phrase_parts) >= 2
                    and not contains_stopword
                    and all(len(part) >= 3 for part in phrase_parts)
                )
                if len(useful) >= 2 or meaningful_domain_phrase:
                    concepts.add(" ".join(phrase_parts))
    return concepts


def shared_bridge_concepts(left: list[str], right: list[str]) -> list[str]:
    return sorted(bridge_concepts(left) & bridge_concepts(right))


def terms_match(left: RagTerm, right: RagTerm) -> bool:
    if is_generic_term(left.term) or is_generic_term(right.term):
        return False
    left_variants = term_variants(left)
    right_variants = term_variants(right)
    if left_variants & right_variants:
        return True
    for left_variant in left_variants:
        for right_variant in right_variants:
            if _meaningful_containment(left_variant, right_variant):
                return True
    return False


def match_rag_terms(new_terms: list[RagTerm], existing_terms: list[RagTerm]) -> list[TermMatch]:
    matches: list[TermMatch] = []
    seen: set[tuple[str, str]] = set()
    for new_term in new_terms:
        if is_generic_term(new_term.term):
            continue
        for existing_term in existing_terms:
            if not terms_match(new_term, existing_term):
                continue
            key = (normalize_term(new_term.term), normalize_term(existing_term.term))
            if key in seen:
                continue
            seen.add(key)
            score = _match_score(new_term, existing_term)
            matches.append(
                TermMatch(
                    term=new_term.term,
                    role=new_term.role,
                    evidence=new_term.evidence,
                    linked_evidence=existing_term.evidence,
                    score=score,
                )
            )
    return sorted(matches, key=lambda match: match.score, reverse=True)


def _match_score(new_term: RagTerm, existing_term: RagTerm) -> int:
    score = new_term.weight + existing_term.weight + ROLE_BONUS.get(new_term.role, 0)
    if normalize_term(new_term.term) == normalize_term(existing_term.term):
        score += 4
    else:
        score += 2
    if " " in normalize_term(new_term.term):
        score += 2
    return score


def _meaningful_containment(left: str, right: str) -> bool:
    left_parts = left.split()
    right_parts = right.split()
    if len(left_parts) < 2 or len(right_parts) < 2:
        return False
    shorter, longer = (left, right) if len(left_parts) <= len(right_parts) else (right, left)
    return f" {shorter} " in f" {longer} "
