"""Synapse construction for the overview neuron map.

Every normalized record already states what it emits (``轴突信号`` / axon signals)
and what it needs (``树突信号`` / dendrite signals), each with a type and its own
evidence. This module pairs those signals across records:

* **axo-dendritic** — one record's axon signal meets another's dendrite signal.
* **axo-axonic** — two records' axon signals meet (``Strong Limitation`` is an
  axon type, so "this contribution / that limitation" lives here).

Pairs are scored with the same machinery the watch pipeline uses
(:mod:`clawshelf.idea`), so every synapse can name the two signals it joined,
their types, and both evidence strings. Validated P1 watch links are projected
onto the same signals as a separate, stronger ``confirmed`` class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import hashlib

from .idea import (
    COMPLEMENTARY_PAIRS,
    CONSOLIDATION_PAIRS,
    content_terms,
    score_signal_pair_with_terms,
)
from .normalize import NormalizedRecord, SignalEntry
from .terms import normalize_term


SYNAPSE_MIN_EVIDENCE = 2
SYNAPSE_MIN_SCORE_WITHOUT_OVERLAP = 13
SYNAPSE_PER_SIGNAL = 2
# Budgeted per (node pair, kind) rather than per node pair: two records usually
# have far more compatible axo-dendritic pairings than axo-axonic ones, and a
# flat budget lets the former crowd the latter out entirely.
SYNAPSE_PER_PAIR = 2
SYNAPSE_PER_NODE = 6
SYNAPSE_GLOBAL_CAP = 400
SYNAPSE_SCAN_MAX_NODES = 400
CONFIRMED_MATCH_RATIO = 0.5

AXO_DENDRITIC = "axo_dendritic"
AXO_AXONIC = "axo_axonic"


def stable_id(*parts: str) -> str:
    """Deterministic short id prefixed by its kind. Shared with ``overview``."""
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{parts[0]}-{digest}"


@dataclass(frozen=True)
class SignalRef:
    """A parsed signal plus everything the synapse pass needs to score it."""

    id: str
    node: str
    polarity: str
    index: int
    entry: SignalEntry
    terms: frozenset[str]


def build_signals(
    node_id: str,
    record: NormalizedRecord,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[SignalRef]]:
    """Return the axon list, dendrite list, and refs for one record."""
    axon: list[dict[str, Any]] = []
    dendrite: list[dict[str, Any]] = []
    refs: list[SignalRef] = []

    for polarity, entries, bucket in (
        ("axon", record.axon_signals, axon),
        ("dendrite", record.dendrite_signals, dendrite),
    ):
        for index, entry in enumerate(entries):
            signal = entry.signal.strip()
            if not signal:
                continue
            signal_type = entry.type.strip() or "unknown"
            evidence = entry.evidence.strip()
            signal_id = stable_id(
                "sig", node_id, polarity, str(index), signal_type, signal
            )
            bucket.append(
                {
                    "id": signal_id,
                    "node": node_id,
                    "polarity": polarity,
                    "index": index,
                    "type": signal_type,
                    "signal": signal,
                    "evidence": evidence,
                    "has_evidence": bool(evidence),
                    "synapse_count": 0,
                }
            )
            refs.append(
                SignalRef(
                    id=signal_id,
                    node=node_id,
                    polarity=polarity,
                    index=index,
                    entry=entry,
                    terms=content_terms(signal),
                )
            )
    return axon, dendrite, refs


def compute_synapses(
    node_ids: list[str],
    refs: dict[str, dict[str, list[SignalRef]]],
    *,
    allowed_pairs: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Score every type-compatible signal pairing, then apply the fan-out caps."""
    candidates: list[dict[str, Any]] = []
    for index, source in enumerate(node_ids):
        for target in node_ids[index + 1 :]:
            if allowed_pairs is not None and (source, target) not in allowed_pairs:
                continue
            candidates.extend(_pair_candidates(source, target, refs))

    candidates.sort(
        key=lambda item: (
            -item["score"],
            -item["components"]["complementarity"],
            -item["components"]["overlap"],
            -item["components"]["evidence"],
            item["id"],
        )
    )

    per_signal: dict[str, int] = {}
    per_pair: dict[tuple[str, str, str], int] = {}
    per_node: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        if len(selected) >= SYNAPSE_GLOBAL_CAP:
            break
        source_signal = candidate["source_signal"]
        target_signal = candidate["target_signal"]
        pair = (candidate["source"], candidate["target"], candidate["kind"])
        if (
            per_signal.get(source_signal, 0) >= SYNAPSE_PER_SIGNAL
            or per_signal.get(target_signal, 0) >= SYNAPSE_PER_SIGNAL
            or per_pair.get(pair, 0) >= SYNAPSE_PER_PAIR
            or per_node.get(candidate["source"], 0) >= SYNAPSE_PER_NODE
            or per_node.get(candidate["target"], 0) >= SYNAPSE_PER_NODE
        ):
            continue
        selected.append(candidate)
        per_signal[source_signal] = per_signal.get(source_signal, 0) + 1
        per_signal[target_signal] = per_signal.get(target_signal, 0) + 1
        per_pair[pair] = per_pair.get(pair, 0) + 1
        per_node[candidate["source"]] = per_node.get(candidate["source"], 0) + 1
        per_node[candidate["target"]] = per_node.get(candidate["target"], 0) + 1

    selected.sort(key=lambda item: (item["source"], item["target"], item["id"]))
    return selected


def _pair_candidates(
    source: str,
    target: str,
    refs: dict[str, dict[str, list[SignalRef]]],
) -> list[dict[str, Any]]:
    """All accepted pairings for one unordered node pair (``source`` < ``target``)."""
    source_refs = refs.get(source, {})
    target_refs = refs.get(target, {})
    candidates: list[dict[str, Any]] = []

    # A.axon -> B.dendrite
    for pre in source_refs.get("axon", []):
        for post in target_refs.get("dendrite", []):
            candidate = _score(source, target, pre, post, AXO_DENDRITIC, True)
            if candidate:
                candidates.append(candidate)
    # B.axon -> A.dendrite (a genuinely different relation, not the mirror)
    for pre in target_refs.get("axon", []):
        for post in source_refs.get("dendrite", []):
            candidate = _score(source, target, post, pre, AXO_DENDRITIC, False)
            if candidate:
                candidates.append(candidate)
    # A.axon <-> B.axon
    for pre in source_refs.get("axon", []):
        for post in target_refs.get("axon", []):
            candidate = _score(source, target, pre, post, AXO_AXONIC, True)
            if candidate:
                candidates.append(candidate)
    return candidates


def _score(
    source: str,
    target: str,
    source_ref: SignalRef,
    target_ref: SignalRef,
    kind: str,
    fires_from_source: bool,
) -> dict[str, Any] | None:
    """Gate cheaply, then score. ``source_ref`` always sits on the ``source`` node."""
    pre, post = (
        (source_ref, target_ref) if fires_from_source else (target_ref, source_ref)
    )
    if not pre.entry.evidence.strip() or not post.entry.evidence.strip():
        return None
    if not _type_compatible(pre.entry.type, post.entry.type):
        return None

    candidate = score_signal_pair_with_terms(
        pre.entry, post.entry, pre.terms, post.terms
    )
    if candidate.evidence_score < SYNAPSE_MIN_EVIDENCE:
        return None
    if (
        candidate.overlap_score < 1
        and candidate.total_score < SYNAPSE_MIN_SCORE_WITHOUT_OVERLAP
    ):
        return None

    score = candidate.total_score
    return {
        "id": stable_id("syn", source_ref.id, target_ref.id, kind),
        "source": source,
        "target": target,
        "source_signal": source_ref.id,
        "target_signal": target_ref.id,
        "kind": kind,
        "class": "computed",
        "direction": "source_to_target" if fires_from_source else "target_to_source",
        "idea_type": _idea_type(candidate),
        "label": _label(pre.entry.type, post.entry.type),
        "score": score,
        "components": {
            "overlap": candidate.overlap_score,
            "complementarity": candidate.complementarity_score,
            "novelty": candidate.novelty_score,
            "evidence": candidate.evidence_score,
            "feasibility": candidate.feasibility_score,
        },
        "strength": round(min(0.95, 0.30 + 0.04 * score), 2),
        "source_signal_type": source_ref.entry.type.strip() or "unknown",
        "target_signal_type": target_ref.entry.type.strip() or "unknown",
        "source_signal_text": source_ref.entry.signal.strip(),
        "target_signal_text": target_ref.entry.signal.strip(),
        "source_evidence": source_ref.entry.evidence.strip(),
        "target_evidence": target_ref.entry.evidence.strip(),
        "also_computed": False,
        "edge": None,
        "created_at": "",
    }


def _type_compatible(left_type: str, right_type: str) -> bool:
    """True when ``_complementarity_score`` would return 3 or 5.

    A tuple lookup that prunes most combinations before any string work.
    """
    pair = (left_type, right_type)
    mirrored = (right_type, left_type)
    return (
        pair in COMPLEMENTARY_PAIRS
        or mirrored in COMPLEMENTARY_PAIRS
        or pair in CONSOLIDATION_PAIRS
        or mirrored in CONSOLIDATION_PAIRS
    )


def _idea_type(candidate: Any) -> str:
    if candidate.idea_type in {"innovation", "consolidation"}:
        return candidate.idea_type
    if (
        candidate.overlap_score >= 1
        and candidate.complementarity_score >= 3
        and candidate.evidence_score >= 4
    ):
        return "relation_candidate"
    return "connection_candidate"


def _label(pre_type: str, post_type: str) -> str:
    return f"{pre_type.strip()} → {post_type.strip()}".strip(" →") or "Signal pairing"


def project_confirmed_synapses(
    edges: list[dict[str, Any]],
    refs: dict[str, dict[str, list[SignalRef]]],
) -> tuple[list[dict[str, Any]], int]:
    """Anchor validated P1 links onto the signals their sparks name.

    Event sparks often paraphrase rather than quote, so an unresolved side falls
    back to the soma (axon hillock) instead of dropping the link. Returns the
    synapses and the number of sides that could not be resolved.
    """
    confirmed: list[dict[str, Any]] = []
    unresolved = 0
    seen: dict[tuple[str, str], dict[str, Any]] = {}

    for edge in edges:
        source_refs = _flat_refs(refs, edge["source"])
        target_refs = _flat_refs(refs, edge["target"])
        for index, spark in enumerate(edge.get("sparks", [])):
            source_ref = _match_signal(str(spark.get("source_signal", "")), source_refs)
            target_ref = _match_signal(str(spark.get("target_signal", "")), target_refs)
            if source_ref is None:
                unresolved += 1
            if target_ref is None:
                unresolved += 1

            kind = AXO_DENDRITIC
            fires_from_source = True
            if source_ref is not None and target_ref is not None:
                if source_ref.polarity == "axon" and target_ref.polarity == "axon":
                    kind = AXO_AXONIC
                elif source_ref.polarity == "dendrite" and target_ref.polarity == "axon":
                    fires_from_source = False
            elif source_ref is not None and source_ref.polarity == "dendrite":
                fires_from_source = False
            elif target_ref is not None and target_ref.polarity == "dendrite":
                fires_from_source = True

            score = spark.get("total_score")
            if not isinstance(score, int):
                score = int(edge.get("creativity_score") or 0)
            synapse = {
                "id": stable_id(
                    "syn",
                    edge["id"],
                    source_ref.id if source_ref else "soma",
                    target_ref.id if target_ref else "soma",
                    str(index),
                ),
                "source": edge["source"],
                "target": edge["target"],
                "source_signal": source_ref.id if source_ref else None,
                "target_signal": target_ref.id if target_ref else None,
                "kind": kind,
                "class": "confirmed",
                "direction": (
                    "source_to_target" if fires_from_source else "target_to_source"
                ),
                "idea_type": spark.get("idea_type") or edge.get("idea_type"),
                "label": spark.get("label") or edge.get("label") or "",
                "score": score,
                "components": {},
                "strength": round(float(edge.get("confidence") or 0.0), 2),
                "source_signal_type": (
                    source_ref.entry.type.strip() if source_ref else ""
                ),
                "target_signal_type": (
                    target_ref.entry.type.strip() if target_ref else ""
                ),
                "source_signal_text": str(spark.get("source_signal", "")).strip(),
                "target_signal_text": str(spark.get("target_signal", "")).strip(),
                "source_evidence": str(spark.get("source_evidence", "")).strip(),
                "target_evidence": str(spark.get("target_evidence", "")).strip(),
                "also_computed": False,
                "edge": edge["id"],
                "created_at": edge.get("created_at", ""),
            }
            if source_ref is not None and target_ref is not None:
                key = (source_ref.id, target_ref.id)
                existing = seen.get(key)
                if existing is not None:
                    if synapse["score"] > existing["score"]:
                        confirmed[confirmed.index(existing)] = synapse
                        seen[key] = synapse
                    continue
                seen[key] = synapse
            confirmed.append(synapse)

    return confirmed, unresolved


def merge_synapses(
    computed: list[dict[str, Any]],
    confirmed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Confirmed links win; a computed duplicate donates its score components."""
    anchored = {
        (item["source_signal"], item["target_signal"]): item
        for item in confirmed
        if item["source_signal"] and item["target_signal"]
    }
    merged: list[dict[str, Any]] = list(confirmed)
    for candidate in computed:
        key = (candidate["source_signal"], candidate["target_signal"])
        duplicate = anchored.get(key)
        if duplicate is not None:
            duplicate["also_computed"] = True
            if not duplicate["components"]:
                duplicate["components"] = candidate["components"]
            continue
        merged.append(candidate)
    merged.sort(
        key=lambda item: (
            0 if item["class"] == "confirmed" else 1,
            item["source"],
            item["target"],
            item["id"],
        )
    )
    return merged


def _flat_refs(
    refs: dict[str, dict[str, list[SignalRef]]],
    node_id: str,
) -> list[SignalRef]:
    buckets = refs.get(node_id, {})
    return [*buckets.get("axon", []), *buckets.get("dendrite", [])]


def _match_signal(text: str, candidates: Iterable[SignalRef]) -> SignalRef | None:
    text = text.strip()
    if not text:
        return None
    normalized = normalize_term(text)
    ordered = sorted(candidates, key=lambda ref: ref.id)
    for ref in ordered:
        if normalized and normalize_term(ref.entry.signal) == normalized:
            return ref

    terms = content_terms(text)
    if not terms:
        return None
    best: SignalRef | None = None
    best_ratio = 0.0
    for ref in ordered:
        if not ref.terms:
            continue
        shared = terms & ref.terms
        if not shared:
            continue
        ratio = len(shared) / min(len(terms), len(ref.terms))
        if ratio > best_ratio:
            best = ref
            best_ratio = ratio
    return best if best_ratio >= CONFIRMED_MATCH_RATIO else None
