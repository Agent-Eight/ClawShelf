from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .config import ConfigError, ShelfConfig, load_or_create_config
from .normalize import NormalizedRecord, parse_normalized_record
from .overview_synapses import (
    SYNAPSE_SCAN_MAX_NODES,
    SignalRef,
    build_signals,
    compute_synapses,
    merge_synapses,
    project_confirmed_synapses,
    stable_id as _stable_id,
)
from .overview_template import render_page
from .terms import is_generic_term, normalize_term


OVERVIEW_SCHEMA = "clawshelf.overview-data/v2"
OVERVIEW_NAME = "clawshelf-overview.html"
SIMILARITY_NEIGHBORS = 3
VALID_IDEA_TYPES = {
    "innovation",
    "consolidation",
    "relation_candidate",
    "connection_candidate",
}
IDEA_PRIORITY = {
    "innovation": 4,
    "consolidation": 3,
    "relation_candidate": 2,
    "connection_candidate": 1,
}


class OverviewError(RuntimeError):
    pass


@dataclass(frozen=True)
class OverviewResult:
    status: str
    path: str
    file_url: str
    markdown_link: str
    node_count: int
    edge_count: int
    warnings: list[str]
    synapse_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": self.path,
            "file_url": self.file_url,
            "markdown_link": self.markdown_link,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "synapse_count": self.synapse_count,
            "warnings": self.warnings,
        }


def generate_overview(
    folder: Path,
    *,
    language: str = "auto",
) -> OverviewResult:
    root = folder.resolve()
    if not root.is_dir():
        raise OverviewError(f"shelf folder does not exist: {root}")

    config = load_or_create_config(root)
    payload, warnings = build_overview_data(root, config, language=language)
    if not payload["nodes"]:
        raise OverviewError(
            "no usable normalized records were found; the existing overview was not changed"
        )

    output = root / "clawshelf" / OVERVIEW_NAME
    rendered = render_overview_html(payload)
    _atomic_write(output, rendered)
    return OverviewResult(
        status="generated",
        path=str(output),
        file_url=output.as_uri(),
        markdown_link=f"[打开概览]({output.as_uri()})",
        node_count=len(payload["nodes"]),
        edge_count=len(payload["edges"]),
        synapse_count=len(payload["synapses"]),
        warnings=warnings,
    )


def build_overview_data(
    root: Path,
    config: ShelfConfig,
    *,
    language: str = "auto",
) -> tuple[dict[str, Any], list[str]]:
    root = root.resolve()
    resolved_language = _resolve_language(language)
    nodes, vectors, source_ids, refs, warnings = _load_nodes(root)
    edges, event_warnings = _load_edges(root, config, source_ids)
    warnings.extend(event_warnings)
    similarity_links = _similarity_links(nodes, vectors)

    node_ids = sorted(node["id"] for node in nodes)
    allowed_pairs: set[tuple[str, str]] | None = None
    if len(node_ids) > SYNAPSE_SCAN_MAX_NODES:
        allowed_pairs = _restricted_pairs(similarity_links, edges)
        warnings.append(
            f"Shelf has {len(node_ids)} sources; synapse scanning was limited to "
            "pairs that already share a semantic link or a validated P1 link."
        )
    computed = compute_synapses(node_ids, refs, allowed_pairs=allowed_pairs)
    confirmed, unresolved = project_confirmed_synapses(edges, refs)
    synapses = merge_synapses(computed, confirmed)
    _attach_synapse_counts(nodes, synapses)

    payload = {
        "schema": OVERVIEW_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": resolved_language,
        "collection": {
            "name": root.name,
            "path": str(root),
            "shelf_plan": config.shelf_plan,
        },
        "nodes": nodes,
        "synapses": synapses,
        "edges": edges,
        "similarity_links": similarity_links,
        "stats": _stats(nodes, synapses, unresolved),
        "warnings": warnings,
        "ui": _ui_strings(resolved_language),
    }
    return payload, warnings


def render_overview_html(payload: dict[str, Any]) -> str:
    try:
        return render_page(_safe_json(payload))
    except (OSError, ValueError) as exc:
        raise OverviewError(str(exc)) from exc


def _restricted_pairs(
    similarity_links: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for link in similarity_links:
        pairs.add(tuple(sorted((link["source"], link["target"]))))  # type: ignore[arg-type]
    for edge in edges:
        pairs.add((edge["source"], edge["target"]))
    return pairs


def _attach_synapse_counts(
    nodes: list[dict[str, Any]],
    synapses: list[dict[str, Any]],
) -> None:
    per_node: dict[str, int] = {}
    per_signal: dict[str, int] = {}
    for synapse in synapses:
        per_node[synapse["source"]] = per_node.get(synapse["source"], 0) + 1
        per_node[synapse["target"]] = per_node.get(synapse["target"], 0) + 1
        for key in ("source_signal", "target_signal"):
            signal_id = synapse[key]
            if signal_id:
                per_signal[signal_id] = per_signal.get(signal_id, 0) + 1
    for node in nodes:
        node["synapse_count"] = per_node.get(node["id"], 0)
        for signal in (*node["axon"], *node["dendrite"]):
            signal["synapse_count"] = per_signal.get(signal["id"], 0)


def _stats(
    nodes: list[dict[str, Any]],
    synapses: list[dict[str, Any]],
    unresolved: int,
) -> dict[str, int]:
    return {
        "nodes": len(nodes),
        "signals": sum(node["signal_count"] for node in nodes),
        "synapses": len(synapses),
        "confirmed": sum(1 for item in synapses if item["class"] == "confirmed"),
        "axo_dendritic": sum(
            1 for item in synapses if item["kind"] == "axo_dendritic"
        ),
        "axo_axonic": sum(1 for item in synapses if item["kind"] == "axo_axonic"),
        "isolates": sum(1 for node in nodes if node["isolate"]),
        "unanchored_confirmed": unresolved,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an interactive ClawShelf overview HTML file."
    )
    parser.add_argument("folder", help="Local ClawShelf working folder.")
    parser.add_argument(
        "--lang",
        choices=("auto", "en", "zh"),
        default="auto",
        help="Overview interface language.",
    )
    args = parser.parse_args(argv)
    output = Path(args.folder).resolve() / "clawshelf" / OVERVIEW_NAME
    try:
        result = generate_overview(Path(args.folder), language=args.lang)
    except ConfigError as exc:
        print(
            json.dumps(
                {
                    "status": "config_invalid",
                    "path": str(output),
                    "file_url": output.as_uri(),
                    "markdown_link": f"[打开概览]({output.as_uri()})",
                    "node_count": 0,
                    "edge_count": 0,
                    "synapse_count": 0,
                    "warnings": [],
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 2
    except (OSError, OverviewError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "path": str(output),
                    "file_url": output.as_uri(),
                    "markdown_link": f"[打开概览]({output.as_uri()})",
                    "node_count": 0,
                    "edge_count": 0,
                    "synapse_count": 0,
                    "warnings": [],
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 3
    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 0


def _load_nodes(
    root: Path,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, float]],
    dict[str, str],
    dict[str, dict[str, list[SignalRef]]],
    list[str],
]:
    normalized = root / "clawshelf" / "normalized"
    paths = sorted(normalized.rglob("*.md")) if normalized.is_dir() else []
    nodes: list[dict[str, Any]] = []
    vectors: dict[str, dict[str, float]] = {}
    source_ids: dict[str, str] = {}
    refs: dict[str, dict[str, list[SignalRef]]] = {}
    warnings: list[str] = []

    for path in paths:
        try:
            record = parse_normalized_record(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except (OSError, ValueError) as exc:
            warnings.append(f"Skipped invalid normalized record {path.name}: {exc}")
            continue
        source = record.frontmatter.get("source", "").strip()
        if not source:
            warnings.append(
                f"Skipped normalized record {path.name}: missing source frontmatter"
            )
            continue
        canonical = _canonical_source(root, source)
        if canonical in source_ids:
            warnings.append(
                f"Skipped duplicate normalized source {source!r}: {path.name}"
            )
            continue
        node_id = _stable_id("node", canonical)
        topics = _bullet_values(record.sections.get("Topics", ""))
        keywords = [item.term for item in record.keywords if item.term]
        rag_terms = [
            {
                "term": item.term,
                "weight": item.weight,
                "aliases": item.aliases,
                "role": item.role,
            }
            for item in record.rag_terms
            if item.term
        ]
        axon, dendrite, signal_refs = build_signals(node_id, record)
        node = {
            "id": node_id,
            "source": source,
            "canonical_source": canonical,
            "title": record.title or Path(source).name or source,
            "type": record.frontmatter.get("source_type", "").strip() or "unknown",
            "topics": topics,
            "keywords": keywords,
            "rag_terms": rag_terms,
            "summary": _plain_text(record.sections.get("Summary", ""))[:1800],
            "confidence": record.frontmatter.get("confidence", "").strip()
            or "Unknown",
            "map_role": _map_role(record),
            "axon": axon,
            "dendrite": dendrite,
            "signal_count": len(axon) + len(dendrite),
            "synapse_count": 0,
            "isolate": not axon and not dendrite,
        }
        nodes.append(node)
        vectors[node_id] = _semantic_vector(record, topics)
        source_ids[canonical] = node_id
        refs[node_id] = {
            "axon": [ref for ref in signal_refs if ref.polarity == "axon"],
            "dendrite": [ref for ref in signal_refs if ref.polarity == "dendrite"],
        }

    nodes.sort(key=lambda item: (item["title"].casefold(), item["id"]))
    return nodes, vectors, source_ids, refs, warnings


def _load_edges(
    root: Path,
    config: ShelfConfig,
    source_ids: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    events_dir = root / "clawshelf" / "events"
    paths = sorted(events_dir.glob("*.json")) if events_dir.is_dir() else []
    threshold = config.creativity_scoring.advanced.threshold
    min_confidence = config.creativity_scoring.advanced.min_confidence
    aggregates: dict[tuple[str, str], dict[str, Any]] = {}
    warnings: list[str] = []

    for path in paths:
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Skipped invalid event {path.name}: {exc}")
            continue
        if not isinstance(event, dict) or (
            event.get("priority") != "P1" and event.get("classification") != "P1"
        ):
            continue
        created_at = str(event.get("created_at", "")).strip()
        links = event.get("linked_sources", [])
        if not isinstance(links, list):
            warnings.append(f"Skipped malformed P1 event {path.name}: linked_sources")
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            score = _number(link.get("creativity_score"))
            confidence = _number(link.get("confidence"))
            evidence = _valid_evidence(link.get("matched_evidence"))
            if (
                link.get("verdict") != "p1_candidate"
                or score is None
                or score < threshold
                or confidence is None
                or confidence < min_confidence
                or not evidence
            ):
                continue
            new_source = _canonical_source(
                root, str(link.get("new_source_path", "")).strip()
            )
            linked_source = _canonical_source(
                root, str(link.get("linked_source_path", "")).strip()
            )
            new_id = source_ids.get(new_source)
            linked_id = source_ids.get(linked_source)
            if not new_id or not linked_id or new_id == linked_id:
                warnings.append(
                    f"Skipped P1 link in {path.name}: source is not in normalized inventory"
                )
                continue
            source_id, target_id = sorted((new_id, linked_id))
            forward = new_id == source_id
            mapped_evidence = [
                {
                    "signal": item["signal"],
                    "why_it_matters": item["why_it_matters"],
                    "source_evidence": (
                        item["new_evidence"]
                        if forward
                        else item["linked_evidence"]
                    ),
                    "target_evidence": (
                        item["linked_evidence"]
                        if forward
                        else item["new_evidence"]
                    ),
                }
                for item in evidence
            ]
            sparks = _sparks(link, forward, mapped_evidence)
            key = (source_id, target_id)
            edge = aggregates.setdefault(
                key,
                {
                    "id": _stable_id("edge", source_id, target_id),
                    "source": source_id,
                    "target": target_id,
                    "idea_type": "connection_candidate",
                    "label": "Evidence-backed connection",
                    "creativity_score": score,
                    "confidence": confidence,
                    "created_at": created_at,
                    "evidence": [],
                    "sparks": [],
                },
            )
            edge["creativity_score"] = max(edge["creativity_score"], score)
            edge["confidence"] = max(edge["confidence"], confidence)
            edge["created_at"] = max(edge["created_at"], created_at)
            edge["evidence"] = _dedupe_dicts(
                [*edge["evidence"], *mapped_evidence]
            )
            edge["sparks"] = _dedupe_dicts([*edge["sparks"], *sparks])
            best = _best_spark(edge["sparks"])
            if best:
                edge["idea_type"] = best["idea_type"]
                edge["label"] = best["label"]

    edges = sorted(
        aggregates.values(),
        key=lambda item: (
            -item["creativity_score"],
            -item["confidence"],
            item["id"],
        ),
    )
    return edges, warnings


def _valid_evidence(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    evidence: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        new_evidence = str(item.get("new_evidence", "")).strip()
        linked_evidence = str(item.get("linked_evidence", "")).strip()
        if not new_evidence or not linked_evidence:
            continue
        evidence.append(
            {
                "signal": str(item.get("signal", "")).strip(),
                "why_it_matters": str(item.get("why_it_matters", "")).strip(),
                "new_evidence": new_evidence,
                "linked_evidence": linked_evidence,
            }
        )
    return evidence


def _sparks(
    link: dict[str, Any],
    forward: bool,
    evidence: list[dict[str, str]],
) -> list[dict[str, Any]]:
    sparks: list[dict[str, Any]] = []
    candidates = link.get("idea_candidates", [])
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            idea_type = str(candidate.get("idea_type", "")).strip()
            if idea_type not in VALID_IDEA_TYPES:
                continue
            new_signal = str(candidate.get("new_signal", "")).strip()
            linked_signal = str(candidate.get("linked_signal", "")).strip()
            new_type = str(candidate.get("new_signal_type", "")).strip()
            linked_type = str(candidate.get("linked_signal_type", "")).strip()
            source_type = new_type if forward else linked_type
            target_type = linked_type if forward else new_type
            sparks.append(
                {
                    "idea_type": idea_type,
                    "label": (
                        f"{source_type} → {target_type}".strip(" →")
                        or "Evidence-backed connection"
                    ),
                    "source_signal": new_signal if forward else linked_signal,
                    "target_signal": linked_signal if forward else new_signal,
                    "source_evidence": (
                        str(candidate.get("new_evidence", "")).strip()
                        if forward
                        else str(candidate.get("linked_evidence", "")).strip()
                    ),
                    "target_evidence": (
                        str(candidate.get("linked_evidence", "")).strip()
                        if forward
                        else str(candidate.get("new_evidence", "")).strip()
                    ),
                    "total_score": _integer(candidate.get("total_score")),
                }
            )
    if not sparks:
        sparks.extend(
            {
                "idea_type": "connection_candidate",
                "label": item["why_it_matters"]
                or item["signal"]
                or "Evidence-backed connection",
                "source_signal": item["signal"],
                "target_signal": "",
                "source_evidence": item["source_evidence"],
                "target_evidence": item["target_evidence"],
                "total_score": None,
            }
            for item in evidence
        )
    return sparks


def _best_spark(sparks: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not sparks:
        return None
    return max(
        sparks,
        key=lambda item: (
            IDEA_PRIORITY.get(item["idea_type"], 0),
            item.get("total_score") or 0,
            item.get("label", ""),
        ),
    )


def _similarity_links(
    nodes: list[dict[str, Any]],
    vectors: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    candidates: list[tuple[float, str, str]] = []
    for index, left in enumerate(nodes):
        for right in nodes[index + 1 :]:
            weight = _weighted_jaccard(vectors[left["id"]], vectors[right["id"]])
            if weight > 0:
                candidates.append((weight, left["id"], right["id"]))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    degree = {node["id"]: 0 for node in nodes}
    selected: list[dict[str, Any]] = []
    for weight, source, target in candidates:
        if (
            degree[source] >= SIMILARITY_NEIGHBORS
            or degree[target] >= SIMILARITY_NEIGHBORS
        ):
            continue
        selected.append(
            {
                "source": source,
                "target": target,
                "weight": round(weight, 4),
            }
        )
        degree[source] += 1
        degree[target] += 1
    return selected


def _semantic_vector(
    record: NormalizedRecord,
    topics: list[str],
) -> dict[str, float]:
    vector: dict[str, float] = {}

    def add(value: str, weight: float) -> None:
        normalized = normalize_term(value)
        if not normalized or is_generic_term(normalized):
            return
        vector[normalized] = max(vector.get(normalized, 0), weight)

    for term in record.rag_terms:
        add(term.term, float(max(1, min(5, term.weight))))
        for alias in term.aliases:
            add(alias, float(max(1, min(4, term.weight - 1))))
    for topic in topics:
        add(topic, 3.0)
    for keyword in record.keywords:
        add(keyword.term, 2.0)
    return vector


def _weighted_jaccard(
    left: dict[str, float],
    right: dict[str, float],
) -> float:
    terms = set(left) | set(right)
    if not terms:
        return 0.0
    numerator = sum(min(left.get(term, 0), right.get(term, 0)) for term in terms)
    denominator = sum(max(left.get(term, 0), right.get(term, 0)) for term in terms)
    return numerator / denominator if denominator else 0.0


def _canonical_source(root: Path, source: str) -> str:
    source = source.strip()
    if not source:
        return ""
    if "://" in source:
        return source
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = root / path
    return str(path.resolve())


def _map_role(record: NormalizedRecord) -> str:
    tags = record.sections.get("Knowledge Map Tags", "")
    match = re.search(r"(?im)^-\s*Map role:\s*(.+)$", tags)
    if match:
        return _clean_role(match.group(1))
    role = record.sections.get("Paper Role in Shelf", "")
    match = re.search(r"(?i)\bMap role:\s*([^\n(]+)", role)
    if match:
        return _clean_role(match.group(1))
    lowered = role.casefold()
    for candidate in (
        "background",
        "method",
        "evidence",
        "contradiction",
        "gap",
        "idea seed",
        "benchmark",
    ):
        if candidate in lowered:
            return candidate
    return "unknown"


def _clean_role(value: str) -> str:
    return re.split(r"\s+\((?:source|evidence):", value, maxsplit=1)[0].strip(
        " .;`"
    )[:120] or "unknown"


def _bullet_values(section: str) -> list[str]:
    values: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            value = stripped[2:].strip().strip("`* ")
            if value:
                values.append(value)
    return values


def _plain_text(value: str) -> str:
    value = re.sub(r"(?m)^#{1,6}\s+", "", value)
    value = re.sub(r"(?m)^\s*[-*]\s+", "", value)
    value = value.replace("`", "").replace("**", "")
    return re.sub(r"\s+", " ", value).strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        unique.setdefault(key, item)
    return list(unique.values())


def _resolve_language(language: str) -> str:
    if language in {"en", "zh"}:
        return language
    locale_name = " ".join(
        value
        for value in (
            os.environ.get("LC_ALL", ""),
            os.environ.get("LC_MESSAGES", ""),
            os.environ.get("LANG", ""),
        )
        if value
    ).lower()
    return "zh" if locale_name.startswith("zh") or " zh" in locale_name else "en"


def _ui_strings(language: str) -> dict[str, str]:
    """Every user-visible string, injected into the page as ``data.ui``.

    Both branches must carry exactly the same keys — a test pins this.
    """
    if language == "zh":
        return {
            "title": "ClawShelf 神经图谱",
            "subtitle": "每条记录是一个神经元：轴突信号向外发出，树突信号向内接收；突触连接的是有证据支撑的信号配对。",
            "search": "搜索标题、来源或主题",
            "all_types": "全部来源类型",
            "all_confidence": "全部置信度",
            "all_roles": "全部图谱角色",
            "all_ideas": "全部想法类型",
            "all_kinds": "全部突触类型",
            "fit": "适应画布",
            "reset": "重置布局",
            "mode_2d": "切换到 3D（测试版）",
            "mode_3d": "切换到 2D",
            "filter_as_source": "仅显示为来源",
            "filter_as_target": "仅显示为目标",
            "legend": "图例",
            "anatomy": "神经元结构",
            "neurons": "神经元",
            "signals": "信号",
            "synapses": "突触",
            "semantic": "隐藏语义连接",
            "inspector": "详情",
            "select_prompt": "选择一个神经元、一条突触，或缩放后点击某个信号末梢查看证据。",
            "no_synapses": "尚未形成突触；所有神经元仍按语义相似度排列。",
            "no_signals": "该记录没有轴突或树突信号，因此没有突触。",
            "isolate": "孤立神经元",
            "warnings": "生成警告",
            "topics": "主题",
            "keywords": "关键词",
            "summary": "摘要",
            "source": "来源",
            "type": "类型",
            "confidence": "置信度",
            "map_role": "图谱角色",
            "idea_type": "想法类型",
            "score": "配对得分",
            "strength": "强度",
            "evidence": "证据",
            "components": "得分构成",
            "overlap": "语义重叠",
            "complementarity": "互补性",
            "novelty": "新颖度",
            "feasibility": "可行性",
            "partners": "连接对象",
            "generated": "生成时间",
            "neuron": "神经元",
            "soma": "胞体",
            "dendrite": "树突",
            "axon": "轴突",
            "bouton": "轴突末梢",
            "synapse": "突触",
            "axon_signals": "轴突信号",
            "dendrite_signals": "树突信号",
            "axo_dendritic": "轴突—树突",
            "axo_axonic": "轴突—轴突",
            "computed": "推算突触",
            "confirmed": "已验证 P1",
            "also_computed": "同时由信号配对推算得出",
            "zoom_hint": "放大可展开每个信号分支",
            "render_error": "图谱渲染失败。",
        }
    return {
        "title": "ClawShelf Neural Map",
        "subtitle": "Each record is a neuron: axon signals fire outward, dendrite signals receive. Synapses join evidence-backed signal pairs.",
        "search": "Search title, source, or topic",
        "all_types": "All source types",
        "all_confidence": "All confidence",
        "all_roles": "All map roles",
        "all_ideas": "All idea types",
        "all_kinds": "All synapse types",
        "fit": "Fit graph",
        "reset": "Reset layout",
        "mode_2d": "Switch to 3D (beta)",
        "mode_3d": "Switch to 2D",
        "filter_as_source": "Show only as source",
        "filter_as_target": "Show only as target",
        "legend": "Legend",
        "anatomy": "Neuron anatomy",
        "neurons": "Neurons",
        "signals": "Signals",
        "synapses": "Synapses",
        "semantic": "Hidden semantic links",
        "inspector": "Inspector",
        "select_prompt": "Select a neuron or a synapse — or zoom in and click a single signal terminal — to inspect its evidence.",
        "no_synapses": "No synapses formed yet; neurons are still arranged by semantic similarity.",
        "no_signals": "This record has no axon or dendrite signals, so it forms no synapses.",
        "isolate": "Isolated neuron",
        "warnings": "Generation warnings",
        "topics": "Topics",
        "keywords": "Keywords",
        "summary": "Summary",
        "source": "Source",
        "type": "Type",
        "confidence": "Confidence",
        "map_role": "Map role",
        "idea_type": "Idea type",
        "score": "Pairing score",
        "strength": "Strength",
        "evidence": "Evidence",
        "components": "Score components",
        "overlap": "Overlap",
        "complementarity": "Complementarity",
        "novelty": "Novelty",
        "feasibility": "Feasibility",
        "partners": "Connected to",
        "generated": "Generated",
        "neuron": "Neuron",
        "soma": "Soma",
        "dendrite": "Dendrite",
        "axon": "Axon",
        "bouton": "Axon terminal",
        "synapse": "Synapse",
        "axon_signals": "Axon signals",
        "dendrite_signals": "Dendrite signals",
        "axo_dendritic": "Axo-dendritic",
        "axo_axonic": "Axo-axonic",
        "computed": "Computed",
        "confirmed": "Validated P1",
        "also_computed": "Also found by signal pairing",
        "zoom_hint": "Zoom in to open each signal branch",
        "render_error": "The map could not be rendered.",
    }



def _safe_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        encoded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
