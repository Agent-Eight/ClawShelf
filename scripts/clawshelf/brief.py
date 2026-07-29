from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .config import ShelfConfig


MANAGED_START = "<!-- clawshelf:p1-synthesis:start -->"
MANAGED_END = "<!-- clawshelf:p1-synthesis:end -->"
IDEA_LIMIT = 3


class BriefUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class BriefUpdateResult:
    status: str
    path: str
    new_connections: int
    candidate_ideas: int
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def update_synthesis_brief(
    root: Path,
    current_event: dict,
    config: ShelfConfig,
) -> BriefUpdateResult:
    shelf_root = root.resolve()
    brief_path = shelf_root / "clawshelf" / "clawshelf-brief.md"
    historical = _historical_p1_events(shelf_root)
    current_connections = _connection_entries([current_event])
    historical_connections = _connection_entries(historical)
    current_ideas = select_candidate_ideas(current_event)
    all_events = [*historical, current_event]
    connections = _dedupe_by_id(_connection_entries(all_events))
    ideas = _dedupe_by_id(
        idea
        for event in all_events
        for idea in select_candidate_ideas(event)
    )

    historical_ids = {item["id"] for item in historical_connections}
    new_connections = sum(
        item["id"] not in historical_ids
        for item in current_connections
    )
    managed = _render_managed_region(
        shelf_root,
        current_event,
        config,
        connections,
        ideas,
    )
    existing = (
        brief_path.read_text(encoding="utf-8")
        if brief_path.is_file()
        else f"# ClawShelf Brief — {shelf_root.name}\n"
    )
    rendered = _replace_managed_region(existing, managed)
    status = "unchanged" if rendered == existing else "updated"
    if status == "updated":
        _atomic_write(brief_path, rendered)
    else:
        new_connections = 0
    return BriefUpdateResult(
        status=status,
        path=str(brief_path),
        new_connections=new_connections,
        candidate_ideas=len(current_ideas),
    )


def select_candidate_ideas(event: dict, limit: int = IDEA_LIMIT) -> list[dict]:
    structured: list[dict] = []
    fallbacks: list[dict] = []
    for link in event.get("linked_sources", []):
        if not isinstance(link, dict):
            continue
        for candidate in link.get("idea_candidates", []):
            if isinstance(candidate, dict):
                structured.append(_structured_idea(link, candidate))
        for evidence in link.get("matched_evidence", []):
            if isinstance(evidence, dict):
                fallbacks.append(_evidence_idea(link, evidence))

    type_priority = {
        "innovation": 3,
        "consolidation": 2,
        "relation_candidate": 1,
    }
    structured.sort(
        key=lambda item: (
            type_priority.get(item["idea_type"], 0),
            item.get("total_score") or 0,
        ),
        reverse=True,
    )
    selected = _dedupe_by_id(structured)[:limit]
    if len(selected) < limit:
        selected_ids = {item["id"] for item in selected}
        selected_content = {_idea_content_key(item) for item in selected}
        for fallback in _dedupe_by_id(fallbacks):
            content_key = _idea_content_key(fallback)
            if (
                fallback["id"] in selected_ids
                or content_key in selected_content
            ):
                continue
            selected.append(fallback)
            selected_ids.add(fallback["id"])
            selected_content.add(content_key)
            if len(selected) >= limit:
                break
    return selected


def failed_brief_update(root: Path, error: Exception) -> BriefUpdateResult:
    return BriefUpdateResult(
        status="failed",
        path=str(root.resolve() / "clawshelf" / "clawshelf-brief.md"),
        new_connections=0,
        candidate_ideas=0,
        error=str(error),
    )


def _structured_idea(link: dict, candidate: dict) -> dict:
    new_signal = str(candidate.get("new_signal", "")).strip()
    linked_signal = str(candidate.get("linked_signal", "")).strip()
    payload = {
        "idea_type": str(candidate.get("idea_type", "")).strip()
        or "relation_candidate",
        "relation": (
            f"{str(candidate.get('new_signal_type', '')).strip()} → "
            f"{str(candidate.get('linked_signal_type', '')).strip()}"
        ).strip(" →"),
        "connection": f"{new_signal} ↔ {linked_signal}".strip(" ↔"),
        "new_source_path": str(link.get("new_source_path", "")).strip(),
        "linked_source_path": str(link.get("linked_source_path", "")).strip(),
        "new_evidence": str(candidate.get("new_evidence", "")).strip(),
        "linked_evidence": str(candidate.get("linked_evidence", "")).strip(),
        "total_score": _optional_int(candidate.get("total_score")),
    }
    payload["id"] = _stable_id(payload)
    return payload


def _evidence_idea(link: dict, evidence: dict) -> dict:
    signal = str(evidence.get("signal", "")).strip()
    payload = {
        "idea_type": "connection_candidate",
        "relation": str(evidence.get("why_it_matters", "")).strip(),
        "connection": signal,
        "new_source_path": str(link.get("new_source_path", "")).strip(),
        "linked_source_path": str(link.get("linked_source_path", "")).strip(),
        "new_evidence": str(evidence.get("new_evidence", "")).strip(),
        "linked_evidence": str(evidence.get("linked_evidence", "")).strip(),
        "total_score": None,
    }
    payload["id"] = _stable_id(payload)
    return payload


def _connection_entries(events: list[dict]) -> list[dict]:
    entries: list[dict] = []
    for event in events:
        for link in event.get("linked_sources", []):
            if not isinstance(link, dict):
                continue
            new_source = str(link.get("new_source_path", "")).strip()
            linked_source = str(link.get("linked_source_path", "")).strip()
            if not new_source or not linked_source:
                continue
            evidence = [
                item
                for item in link.get("matched_evidence", [])
                if isinstance(item, dict)
            ][:3]
            identity = {
                "new_source_path": new_source,
                "linked_source_path": linked_source,
                "evidence": evidence,
            }
            entries.append(
                {
                    "id": _stable_id(identity),
                    "new_source_path": new_source,
                    "linked_source_path": linked_source,
                    "reason": str(event.get("reason", "")).strip(),
                    "created_at": str(event.get("created_at", "")).strip(),
                    "creativity_score": link.get("creativity_score"),
                    "confidence": link.get("confidence"),
                    "evidence": evidence,
                }
            )
    return entries


def _historical_p1_events(root: Path) -> list[dict]:
    events_dir = root / "clawshelf" / "events"
    if not events_dir.is_dir():
        return []
    events: list[dict] = []
    for path in sorted(events_dir.glob("*-p1.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        links = event.get("linked_sources")
        if (
            event.get("priority") == "P1"
            and isinstance(links, list)
            and all(
                isinstance(link, dict)
                and link.get("new_source_path")
                and link.get("linked_source_path")
                for link in links
            )
        ):
            events.append(event)
    return events


def _render_managed_region(
    root: Path,
    event: dict,
    config: ShelfConfig,
    connections: list[dict],
    ideas: list[dict],
) -> str:
    updated = str(event.get("created_at", "")).strip() or datetime.now(
        timezone.utc
    ).isoformat()
    normalized = root / "clawshelf" / "normalized"
    source_count = len(list(normalized.glob("**/*.md"))) if normalized.is_dir() else 0
    plan = config.shelf_plan
    plan_summary = " / ".join(
        value
        for value in (
            plan.get("domain_background", ""),
            plan.get("work_direction", ""),
            plan.get("concrete_problem", ""),
            plan.get("companion_mode", ""),
        )
        if value
    ) or "unknown"
    lines = [
        MANAGED_START,
        "## Auto-Managed P1 Synthesis",
        "",
        f"- Indexed sources: {source_count}",
        f"- Shelf Plan: {plan_summary}",
        f"- Updated: {updated}",
        "",
        "### Research Connections",
        "",
    ]
    if connections:
        for connection in connections:
            lines.extend(_render_connection(connection))
    else:
        lines.append("- No P1 research connections recorded.")
    lines.extend(["", "### Candidate Ideas", ""])
    if ideas:
        for idea in ideas:
            lines.extend(_render_idea(idea))
    else:
        lines.append("- No evidence-backed candidate ideas recorded.")
    lines.extend([MANAGED_END, ""])
    return "\n".join(lines)


def _render_connection(connection: dict) -> list[str]:
    lines = [
        (
            f"#### `{_source_label(connection['new_source_path'])}` ↔ "
            f"`{_source_label(connection['linked_source_path'])}`"
        ),
        f"<!-- clawshelf:connection:{connection['id']} -->",
    ]
    if connection.get("reason"):
        lines.append(f"- Why: {connection['reason']}")
    score = connection.get("creativity_score")
    confidence = connection.get("confidence")
    if score is not None or confidence is not None:
        parts = []
        if score is not None:
            parts.append(f"creativity score {score}")
        if confidence is not None:
            parts.append(f"confidence {confidence}")
        lines.append(f"- Gate evidence: {', '.join(parts)}")
    for evidence in connection.get("evidence", []):
        lines.append(
            "- Evidence: "
            f"{str(evidence.get('signal', '')).strip()} — "
            f"`{_source_label(connection['new_source_path'])}` "
            f"{str(evidence.get('new_evidence', '')).strip()} ↔ "
            f"`{_source_label(connection['linked_source_path'])}` "
            f"{str(evidence.get('linked_evidence', '')).strip()}"
        )
    lines.append("")
    return lines


def _render_idea(idea: dict) -> list[str]:
    label = _idea_label(idea["idea_type"])
    relation = idea.get("relation") or "evidence-backed connection"
    lines = [
        f"#### [{label}] {relation}",
        f"<!-- clawshelf:idea:{idea['id']} -->",
        f"- Hypothesis: {idea.get('connection') or relation}",
        (
            f"- Sources: `{_source_label(idea['new_source_path'])}` ↔ "
            f"`{_source_label(idea['linked_source_path'])}`"
        ),
        (
            f"- Evidence: `{_source_label(idea['new_source_path'])}` "
            f"{idea.get('new_evidence', '')} ↔ "
            f"`{_source_label(idea['linked_source_path'])}` "
            f"{idea.get('linked_evidence', '')}"
        ),
    ]
    if idea.get("total_score") is not None:
        lines.append(f"- Total score: {idea['total_score']}")
    lines.append("")
    return lines


def _replace_managed_region(existing: str, managed: str) -> str:
    start = existing.find(MANAGED_START)
    end = existing.find(MANAGED_END)
    if (start == -1) != (end == -1):
        raise BriefUpdateError("synthesis brief has an incomplete managed region")
    if start == -1:
        return existing.rstrip() + "\n\n" + managed
    if end < start:
        raise BriefUpdateError("synthesis brief managed-region markers are reversed")
    end += len(MANAGED_END)
    prefix = existing[:start].rstrip()
    suffix = existing[end:].lstrip()
    rendered = prefix + "\n\n" + managed.rstrip()
    if suffix:
        rendered += "\n\n" + suffix
    return rendered.rstrip() + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _dedupe_by_id(items) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in items:
        unique.setdefault(item["id"], item)
    return list(unique.values())


def _stable_id(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _idea_content_key(idea: dict) -> tuple[str, ...]:
    return (
        str(idea.get("new_source_path", "")).strip(),
        str(idea.get("linked_source_path", "")).strip(),
        str(idea.get("connection", "")).strip(),
        str(idea.get("new_evidence", "")).strip(),
        str(idea.get("linked_evidence", "")).strip(),
    )


def _source_label(source: str) -> str:
    return source if "://" in source else Path(source).name


def _idea_label(idea_type: str) -> str:
    return {
        "innovation": "创新",
        "consolidation": "巩固",
        "relation_candidate": "关系候选",
        "connection_candidate": "连接候选",
    }.get(idea_type, idea_type or "候选")


def _optional_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
