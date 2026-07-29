from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from clawshelf.watch import WatchResult, handle_files, watch_folder
from clawshelf.brief import select_candidate_ideas
from clawshelf.events import CreativityScoringOptions
from clawshelf.keyword_worker import KeywordExtractionPacket, run_openclaw_keyword_worker
from clawshelf.creativity_score import CreativityScoreRequest, run_openclaw_creativity_scorer
from clawshelf.config import ConfigError, ShelfConfig, effective_config, load_or_create_config
from clawshelf.semantic_retrieval import qmd_semantic_retriever


NOTIFICATION_SCHEMA = "clawshelf.notification"
DELIVERY_POLICY_SCHEMA = "clawshelf.delivery-policy"
NOTIFY_STATE_SCHEMA = "clawshelf.notify-state"
MAX_DELIVERY_ATTEMPTS = 3


def build_notification(
    event_path: Path,
    event: dict,
    notification_policy: str = "p1_p2",
    session_key: str | None = None,
    channel: str = "last",
    agent_id: str | None = None,
    reply_to: str | None = None,
    reply_account: str | None = None,
) -> dict:
    priority = str(event.get("priority", "")).upper()
    should_notify = priority == "P1" or (priority == "P2" and notification_policy == "p1_p2")
    delivery_mode = "session_key" if session_key else "channel"
    reply_to = reply_to or _reply_target(channel, session_key)
    reply_account = reply_account or _reply_account(channel, session_key)
    notification = {
        "schema": NOTIFICATION_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "event_path": str(event_path),
        "event": event,
        "priority": priority,
        "enabled": should_notify,
        "delivery": "owner_dm",
        "router": "openclaw_delivery_turn",
        "delivery_mode": delivery_mode,
        "summary": _summary(event) if should_notify else "",
        "message": _message(event) if should_notify else "",
        "status": "pending" if should_notify else "log_only",
        "policy": {
            "schema": DELIVERY_POLICY_SCHEMA,
            "mode": "openclaw_delivery_turn",
            "delivery_mode": delivery_mode,
            "agent_id": agent_id,
            "channel": channel,
            "p1": "deliver",
            "p2": "deliver" if notification_policy == "p1_p2" else "log_only",
            "configured_policy": notification_policy,
            "best_effort": True,
        },
    }
    if session_key:
        notification["session_key"] = session_key
        notification["policy"]["session_key"] = session_key
    if reply_to:
        notification["policy"]["reply_to"] = reply_to
    if reply_account:
        notification["policy"]["reply_account"] = reply_account
    return notification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OpenClaw adapter for ClawShelf watch events and P1/P2 notifications."
    )
    parser.add_argument("folder", help="Local ClawShelf working folder to watch.")
    parser.add_argument("--once", nargs="*", help="Process specific files once instead of watching.")
    parser.add_argument("--refresh-command", help="Optional host refresh command with {folder} and {paths}.")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Fallback polling interval.")
    parser.add_argument("--notification-policy", choices=["p1_only", "p1_p2"], help="One-run notification delivery override.")
    parser.add_argument(
        "--no-deliver",
        action="store_true",
        help="Write a non-retryable delivery_disabled notification without calling OpenClaw delivery.",
    )
    parser.add_argument("--agent-id", default=os.environ.get("OPENCLAW_AGENT_ID"), help="Runtime OpenClaw agent for delivery turns.")
    parser.add_argument("--channel", default=os.environ.get("CLAWSHELF_DELIVERY_CHANNEL", "last"), help="OpenClaw delivery channel abstraction.")
    parser.add_argument("--session-key", default=os.environ.get("OPENCLAW_SESSION_KEY"), help="OpenClaw session key to bind notification delivery.")
    parser.add_argument("--reply-to", help="Owner delivery target bound by /clawshelf use.")
    parser.add_argument("--reply-account", help="Delivery account bound by /clawshelf use.")
    parser.add_argument("--openclaw-bin", default=os.environ.get("OPENCLAW_BIN", "openclaw"), help="OpenClaw CLI binary.")
    parser.add_argument(
        "--creativity-scorer",
        choices=["auto", "off", "required"],
        default=None,
        help="Use a host LLM after candidate retrieval.",
    )
    parser.add_argument(
        "--creativity-model",
        default=None,
        help="Host-owned model alias for creativity scoring.",
    )
    parser.add_argument("--creativity-threshold", type=int)
    parser.add_argument("--creativity-min-confidence", type=float)
    parser.add_argument("--candidate-limit", type=int)
    parser.add_argument("--novelty-preference", type=float)
    parser.add_argument(
        "--semantic-retrieval",
        choices=["auto", "off", "required"],
        help="Use QMD vector search only to fill the creativity candidate set.",
    )
    parser.add_argument("--semantic-candidate-target", type=int)
    parser.add_argument(
        "--qmd-bin",
        default=os.environ.get("QMD_BIN", "qmd"),
        help="QMD CLI binary.",
    )
    parser.add_argument("--keyword-model", default=os.environ.get("CLAWSHELF_KEYWORD_MODEL"), help="Optional host-owned model override for keyword extraction.")
    args = parser.parse_args(argv)
    try:
        _validate_agent_route(args.agent_id, args.session_key)
    except ConfigError as exc:
        parser.error(str(exc))

    folder = Path(args.folder).resolve()
    try:
        config = effective_config(load_or_create_config(folder), args)
    except (ConfigError, ValueError) as exc:
        parser.error(str(exc))
    creativity_options = _creativity_options(folder, args, config)
    keyword_worker = keyword_worker_from_args(args)
    keyword_model = args.keyword_model or ""
    delivery_args = {
        "agent_id": args.agent_id,
        "channel": args.channel,
        "session_key": args.session_key,
        "openclaw_bin": args.openclaw_bin,
        "reply_to": args.reply_to,
        "reply_account": args.reply_account,
    }

    if not args.no_deliver:
        retry_pending_notifications(folder, **delivery_args)

    if args.once is None:
        return watch_folder(
            folder,
            args.refresh_command,
            args.poll_seconds,
            creativity_options=creativity_options,
            keyword_worker=keyword_worker,
            keyword_model=keyword_model,
            config=config,
            emit_result=lambda result: _handle_result_and_retry(
                folder, result, config.notification_policy, deliver=not args.no_deliver, **delivery_args
            ),
        )

    result = handle_files(
        folder,
        [Path(path) for path in args.once],
        args.refresh_command,
        creativity_options=creativity_options,
        keyword_worker=keyword_worker,
        keyword_model=keyword_model,
        config=config,
    )
    _handle_result(
        result,
        config.notification_policy,
        deliver=not args.no_deliver,
        **delivery_args,
    )
    if not args.no_deliver:
        retry_pending_notifications(folder, **delivery_args)
    return 0


def write_notification(event_path: Path, notification: dict) -> Path:
    notifications_dir = event_path.parent.parent / "notifications"
    notifications_dir.mkdir(parents=True, exist_ok=True)
    path = notifications_dir / f"{event_path.stem}.notification.json"
    path.write_text(json.dumps(notification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def deliver_notification(
    notification: dict,
    agent_id: str | None = None,
    channel: str = "last",
    session_key: str | None = None,
    openclaw_bin: str = "openclaw",
    reply_to: str | None = None,
    reply_account: str | None = None,
) -> dict:
    if not notification.get("enabled"):
        return {"status": "skipped", "reason": "notification disabled"}
    if not shutil.which(openclaw_bin):
        return {"status": "failed", "reason": f"OpenClaw binary not found: {openclaw_bin}"}
    reply_to = reply_to or _reply_target(channel, session_key)
    reply_account = reply_account or _reply_account(channel, session_key)
    if not agent_id:
        return {
            "status": "failed",
            "reason": "Notification delivery requires the agent bound by /clawshelf use",
        }
    if channel == "feishu" and not reply_to:
        return {
            "status": "failed",
            "reason": "Cannot derive the Feishu user target from the bound session key",
        }

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as prompt:
        prompt.write(_delivery_prompt(notification))
        prompt_path = Path(prompt.name)

    command = [openclaw_bin, "agent"]
    command.extend(["--agent", agent_id])
    command.extend(["--channel", channel])
    if session_key:
        command.extend(["--session-key", session_key])
    if reply_to:
        command.extend(["--reply-channel", channel, "--reply-to", reply_to])
    if reply_account:
        command.extend(["--reply-account", reply_account])
    command.extend(["--deliver", "--message-file", str(prompt_path)])

    try:
        try:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            return {"status": "failed", "reason": "OpenClaw delivery timed out after 120s"}
        except OSError as exc:
            return {"status": "failed", "reason": f"OpenClaw delivery failed: {exc}"}
    finally:
        prompt_path.unlink(missing_ok=True)

    status = "turn_succeeded" if completed.returncode == 0 else "failed"
    receipt = {
        "status": status,
        "router": "openclaw_delivery_turn",
        "delivery_mode": "session_key" if session_key else "channel",
        "agent_id": agent_id,
        "channel": channel,
        "returncode": completed.returncode,
    }
    if session_key:
        receipt["session_key"] = session_key
    if reply_to:
        receipt["reply_to"] = reply_to
    if reply_account:
        receipt["reply_account"] = reply_account
    if completed.stderr:
        receipt["error"] = completed.stderr.strip()[-1000:]
    return receipt


def _reply_target(channel: str, session_key: str | None) -> str | None:
    """Derive owner-DM delivery target from the session bound by /clawshelf use."""
    if str(channel or "").strip().lower() != "feishu" or not session_key:
        return None
    for component in reversed(str(session_key).split(":")):
        value = component.strip()
        if value.startswith("ou_"):
            return f"user:{value}"
    return None


def _reply_account(channel: str, session_key: str | None) -> str | None:
    if str(channel or "").strip().lower() != "feishu" or not session_key:
        return None
    components = [item.strip() for item in str(session_key).split(":") if item.strip()]
    if not components:
        return None
    if components[0] == "agent" and len(components) > 1:
        return components[1]
    return components[0]


def _validate_agent_route(agent_id: str | None, session_key: str | None) -> None:
    if not agent_id or not session_key:
        raise ConfigError(
            "Watcher runtime requires the agent and canonical session bound by /clawshelf use."
        )
    parts = [item.strip() for item in str(session_key).split(":")]
    if len(parts) < 4 or parts[0] != "agent" or not parts[1]:
        raise ConfigError(
            "Watcher runtime requires a canonical session key in the form "
            "agent:<agent-id>:<channel>:..."
        )
    if parts[1] != agent_id:
        raise ConfigError(
            f"Watcher agent {agent_id!r} does not match session agent {parts[1]!r}."
        )


def creativity_runner_from_args(args: argparse.Namespace):
    def run(request: CreativityScoreRequest, model: str):
        return run_openclaw_creativity_scorer(
            request,
            model,
            openclaw_bin=args.openclaw_bin,
            session_key=args.session_key,
            agent_id=args.agent_id,
            channel=args.channel,
        )

    return run


def keyword_worker_from_args(args: argparse.Namespace):
    def run(packet: KeywordExtractionPacket, model: str, *, checkpoint_dir: Path | None = None):
        return run_openclaw_keyword_worker(
            packet,
            model,
            openclaw_bin=args.openclaw_bin,
            session_key=args.session_key,
            agent_id=args.agent_id,
            channel=args.channel,
            checkpoint_dir=checkpoint_dir,
        )

    return run


def _creativity_options(folder: Path, args: argparse.Namespace, config: ShelfConfig | None = None) -> CreativityScoringOptions:
    config = config or effective_config(load_or_create_config(folder), args)
    creativity = config.creativity_scoring
    mode = creativity.mode
    return CreativityScoringOptions(
        mode=mode,
        model=creativity.model,
        creativity_threshold=creativity.advanced.threshold,
        min_confidence=creativity.advanced.min_confidence,
        candidate_limit=creativity.candidate_limit,
        novelty_preference=creativity.novelty_preference,
        semantic_retrieval=creativity.semantic_retrieval,
        semantic_candidate_target=creativity.semantic_candidate_target,
        shelf_plan=config.shelf_plan,
        runner=creativity_runner_from_args(args) if mode != "off" else None,
        semantic_retriever=(
            qmd_semantic_retriever(
                folder,
                qmd_bin=getattr(args, "qmd_bin", None)
                or os.environ.get("QMD_BIN", "qmd"),
            )
            if creativity.semantic_retrieval != "off"
            else None
        ),
    )


def _handle_result(
    result: WatchResult,
    notification_policy: str,
    deliver: bool,
    agent_id: str | None,
    channel: str,
    session_key: str | None,
    openclaw_bin: str,
    reply_to: str | None = None,
    reply_account: str | None = None,
) -> None:
    if result is None:
        return
    event_path, event = result
    notification = build_notification(
        event_path,
        event,
        notification_policy,
        session_key,
        channel,
        agent_id,
        reply_to,
        reply_account,
    )
    priority = str(event.get("priority", "")).upper()
    notification_path = None
    if notification["enabled"]:
        hashes = _event_source_hashes(event_path, event)
        if _hashes_cover_event(event, hashes) and _already_delivered(
            event_path,
            hashes,
            priority,
        ):
            event["status"] = "suppressed_duplicate"
            if event_path.parent.is_dir():
                event_path.write_text(json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            notification["status"] = "suppressed_duplicate"
            notification["source_hashes"] = hashes
            notification_path = write_notification(event_path, notification)
            output = {"notification_path": str(notification_path), **notification}
            print(json.dumps(output, ensure_ascii=False))
            return
        notification_path = write_notification(event_path, notification)
        if deliver:
            notification["receipt"] = deliver_notification(
                notification,
                agent_id,
                channel,
                session_key,
                openclaw_bin,
                reply_to,
                reply_account,
            )
            notification["status"] = notification["receipt"]["status"]
            notification["attempts"] = 1
            notification["source_hashes"] = hashes
            write_notification(event_path, notification)
            if notification["status"] == "turn_succeeded":
                _record_delivered(event_path, hashes, priority)
        else:
            notification["status"] = "delivery_disabled"
            notification["attempts"] = 0
            notification["source_hashes"] = hashes
            write_notification(event_path, notification)
    output = {"notification_path": str(notification_path) if notification_path else "", **notification}
    print(json.dumps(output, ensure_ascii=False))


def _handle_result_and_retry(
    folder: Path,
    result: WatchResult,
    notification_policy: str,
    deliver: bool,
    agent_id: str | None,
    channel: str,
    session_key: str | None,
    openclaw_bin: str,
    reply_to: str | None = None,
    reply_account: str | None = None,
) -> None:
    _handle_result(
        result,
        notification_policy,
        deliver,
        agent_id,
        channel,
        session_key,
        openclaw_bin,
        reply_to,
        reply_account,
    )
    if deliver:
        retry_pending_notifications(
            folder,
            agent_id,
            channel,
            session_key,
            openclaw_bin,
            reply_to,
            reply_account,
        )


def retry_pending_notifications(
    folder: Path,
    agent_id: str | None = None,
    channel: str = "last",
    session_key: str | None = None,
    openclaw_bin: str = "openclaw",
    reply_to: str | None = None,
    reply_account: str | None = None,
) -> None:
    notifications_dir = folder.resolve() / "clawshelf" / "notifications"
    if not notifications_dir.is_dir():
        return
    for path in sorted(notifications_dir.glob("*.notification.json")):
        try:
            notification = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if notification.get("status") not in {"pending", "failed"}:
            continue
        attempts = _attempt_count(notification)
        route_changed = _notification_route_changed(
            notification,
            agent_id,
            channel,
            session_key,
            reply_to,
            reply_account,
        )
        if route_changed:
            attempts = 0
            _bind_notification_route(
                notification,
                agent_id,
                channel,
                session_key,
                reply_to,
                reply_account,
            )
        if attempts >= MAX_DELIVERY_ATTEMPTS:
            continue
        event_path_value = str(notification.get("event_path", "")).strip()
        event_path = Path(event_path_value) if event_path_value else None
        event = notification.get("event") or {}
        hashes = notification.get("source_hashes") or (
            _event_source_hashes(event_path, event) if event_path else {}
        )
        priority = str(event.get("priority", "")).upper()
        if (
            event_path
            and _hashes_cover_event(event, hashes)
            and _already_delivered(event_path, hashes, priority)
        ):
            notification["status"] = "suppressed_duplicate"
            notification["source_hashes"] = hashes
            path.write_text(json.dumps(notification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            continue
        receipt = deliver_notification(
            notification,
            agent_id,
            channel,
            session_key,
            openclaw_bin,
            reply_to,
            reply_account,
        )
        notification["receipt"] = receipt
        notification["status"] = receipt["status"]
        notification["attempts"] = attempts + 1
        path.write_text(json.dumps(notification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if notification["status"] == "turn_succeeded":
            if event_path:
                _record_delivered(event_path, hashes, priority)


def _notification_route_changed(
    notification: dict,
    agent_id: str | None,
    channel: str,
    session_key: str | None,
    reply_to: str | None,
    reply_account: str | None,
) -> bool:
    policy = notification.get("policy")
    policy = policy if isinstance(policy, dict) else {}
    stored_channel = str(policy.get("channel") or "").strip()
    stored_session = str(
        notification.get("session_key") or policy.get("session_key") or ""
    ).strip()
    stored_reply_to = str(policy.get("reply_to") or "").strip()
    stored_reply_account = str(policy.get("reply_account") or "").strip()
    stored_agent = str(policy.get("agent_id") or "").strip()
    current_reply_to = reply_to or _reply_target(channel, session_key)
    current_reply_account = reply_account or _reply_account(channel, session_key)
    return (
        stored_agent != str(agent_id or "").strip()
        or stored_channel != str(channel or "").strip()
        or stored_session != str(session_key or "").strip()
        or stored_reply_to != str(current_reply_to or "").strip()
        or stored_reply_account
        != str(current_reply_account or "").strip()
    )


def _bind_notification_route(
    notification: dict,
    agent_id: str | None,
    channel: str,
    session_key: str | None,
    reply_to: str | None,
    reply_account: str | None,
) -> None:
    policy = notification.setdefault("policy", {})
    delivery_mode = "session_key" if session_key else "channel"
    notification["delivery_mode"] = delivery_mode
    notification["status"] = "pending"
    notification["attempts"] = 0
    policy["channel"] = channel
    policy["agent_id"] = agent_id
    policy["delivery_mode"] = delivery_mode
    if session_key:
        notification["session_key"] = session_key
        policy["session_key"] = session_key
    else:
        notification.pop("session_key", None)
        policy.pop("session_key", None)
    reply_to = reply_to or _reply_target(channel, session_key)
    if reply_to:
        policy["reply_to"] = reply_to
    else:
        policy.pop("reply_to", None)
    reply_account = reply_account or _reply_account(channel, session_key)
    if reply_account:
        policy["reply_account"] = reply_account
    else:
        policy.pop("reply_account", None)


def _attempt_count(notification: dict) -> int:
    try:
        return max(0, int(notification.get("attempts", 0)))
    except (TypeError, ValueError):
        return 0


def _event_source_hashes(event_path: Path, event: dict) -> dict[str, str]:
    root = event_path.parent.parent.parent
    wanted = {str(Path(path).resolve()) for path in event.get("new_files", []) if path}
    found: dict[str, str] = {}
    normalized_dir = root / "clawshelf" / "normalized"
    for record in normalized_dir.glob("**/*.md") if normalized_dir.is_dir() else []:
        try:
            text = record.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source = _frontmatter_value(text, "source")
        sha256 = _frontmatter_value(text, "source_sha256")
        if not source or not sha256:
            continue
        source_path = Path(source)
        resolved = source_path.resolve() if source_path.is_absolute() else (root / source_path).resolve()
        if str(resolved) in wanted:
            found[str(resolved)] = sha256
    return found


def _frontmatter_value(text: str, key: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            return ""
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def _already_delivered(
    event_path: Path,
    hashes: dict[str, str],
    notification_kind: str,
) -> bool:
    delivered = _load_notify_state(event_path).get("delivered", {})
    return bool(hashes) and all(
        delivered.get(f"{notification_kind}:{path}") == sha256
        for path, sha256 in hashes.items()
    )


def _hashes_cover_event(event: dict, hashes: dict[str, str]) -> bool:
    sources = {str(Path(path).resolve()) for path in event.get("new_files", []) if path}
    return bool(sources) and sources == set(hashes)


def _record_delivered(
    event_path: Path,
    hashes: dict[str, str],
    notification_kind: str,
) -> None:
    if not hashes:
        return
    state = _load_notify_state(event_path)
    delivered = state.setdefault("delivered", {})
    delivered.update(
        {f"{notification_kind}:{path}": sha256 for path, sha256 in hashes.items()}
    )
    state_path = event_path.parent.parent / "notify-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=state_path.parent, prefix=f".{state_path.name}.", delete=False
    ) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, state_path)


def _load_notify_state(event_path: Path) -> dict:
    path = event_path.parent.parent / "notify-state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": NOTIFY_STATE_SCHEMA, "delivered": {}}
    if not isinstance(state, dict) or not isinstance(state.get("delivered"), dict):
        return {"schema": NOTIFY_STATE_SCHEMA, "delivered": {}}
    state["schema"] = NOTIFY_STATE_SCHEMA
    return state


def _summary(event: dict) -> str:
    files = ", ".join(Path(path).name for path in event.get("new_files", []))
    reason = event.get("reason") or "ClawShelf 检测到文件变化。"
    if event.get("priority") == "P2":
        return f"P2 ClawShelf 入库：{files}。"
    spark = event.get("idea_spark") or ""
    linked = event.get("linked_sources") or []
    linked_names = ", ".join(
        _source_label(str(item.get("linked_source_path", "")))
        for item in linked[:3]
        if item.get("linked_source_path")
    )
    parts = [f"{event.get('priority', 'P?')} ClawShelf 事件：{files}。{reason}"]
    if spark:
        parts.append(spark)
    if linked_names:
        parts.append(f"相关来源：{linked_names}。")
    return " ".join(parts)


def _message(event: dict) -> str:
    priority = event.get("priority", "P?")
    if priority == "P2":
        lines = [
            "**P2 ClawShelf：新来源已完成入库**",
            "",
            "**新来源**",
            *_code_block_items(_file_names(event)),
        ]
        key_argument_lines = _p2_key_argument_lines(event)
        lines.extend(
            [
                "",
                "**关键论点（来自 Normalization）**",
                *(
                    key_argument_lines
                    or ["- Normalization 未产出可验证的关键论点。"]
                ),
            ]
        )
        return "\n".join(lines)

    files = _file_names(event)
    linked_sources = _linked_source_labels(event)
    matched_signal_cards = _matched_signal_cards(event)
    signals = _matched_terms(event)
    reason = event.get("reason") or "ClawShelf 检测到文件变化。"

    lines = [
        "**P1 ClawShelf：发现潜在研究连接**",
        "",
        "**新来源**",
        *_code_block_items(files),
        "",
        "**为什么推送**",
        reason,
    ]
    if linked_sources:
        lines.extend(
            [
                "",
                "**可能相关的来源**",
                *_code_block_items(linked_sources, bullet=True),
            ]
        )
    if matched_signal_cards:
        lines.extend(["", "**匹配信号**", *matched_signal_cards])
    elif signals:
        lines.extend(["", "**匹配信号**", f"候选关键词：{' · '.join(f'`{term}`' for term in signals)}"])
    lines.extend(["", "**Synthesis Brief**", _brief_update_message(event)])
    idea_cards = _idea_cards(event)
    if idea_cards:
        lines.extend(["", "**候选 Ideas**", *idea_cards])
    return "\n".join(lines)


def _delivery_prompt(notification: dict) -> str:
    return (
        "You are an OpenClaw delivery turn. Send the following ClawShelf "
        "notification to the owner by returning exactly the notification body. "
        "Do not call external APIs, do not inspect files, and do not add analysis.\n\n"
        "<notification>\n"
        f"{notification.get('message', '')}\n"
        "</notification>\n"
    )


def _file_names(event: dict) -> list[str]:
    return [Path(path).name for path in event.get("new_files", []) if path]


def _linked_source_labels(event: dict) -> list[str]:
    sources: list[str] = []
    for item in event.get("linked_sources", []):
        source = str(item.get("linked_source_path", "")).strip()
        if source:
            sources.append(_source_label(source))
    return sources


def _p2_key_argument_lines(event: dict) -> list[str]:
    outcomes = [
        outcome
        for outcome in event.get("normalization_outcomes", [])
        if isinstance(outcome, dict) and outcome.get("key_arguments")
    ]
    lines: list[str] = []
    for outcome in outcomes:
        source = str(outcome.get("source") or "").strip()
        lines.append(f"**`{_source_label(source) if source else 'unknown'}`**")
        for argument in outcome.get("key_arguments", [])[:5]:
            value = str(argument).strip()
            if value:
                lines.append(f"- {value}")
    return lines


def _matched_terms(event: dict) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for item in event.get("linked_sources", []):
        for term in item.get("matched_terms", []):
            normalized = str(term).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                terms.append(normalized)
            if len(terms) >= 8:
                return terms
    return terms


def _matched_signal_cards(event: dict) -> list[str]:
    cards: list[str] = []
    for item in event.get("linked_sources", []):
        new_source = str(item.get("new_source_path", "")).strip()
        linked_source = str(item.get("linked_source_path", "")).strip()
        new_name = _source_label(new_source) if new_source else "unknown"
        linked_name = _source_label(linked_source) if linked_source else "unknown"
        for signal in item.get("matched_evidence", []):
            term = str(signal.get("signal", "")).strip()
            if not term:
                continue
            evidence = str(signal.get("new_evidence", "")).strip() or "new source"
            linked_evidence = str(signal.get("linked_evidence", "")).strip() or "linked record"
            why = str(signal.get("why_it_matters", "")).strip()
            card = [
                f"**{len(cards) + 1}. 连接**",
                term,
                f"新来源：`{new_name}` {evidence}",
                f"关联来源：`{linked_name}` {linked_evidence}",
            ]
            if why:
                card.append(f"关系：{why}")
            cards.append("\n".join(card))
            if len(cards) >= 8:
                return cards
    return cards


def _brief_update_message(event: dict) -> str:
    update = event.get("synthesis_brief_update") or {}
    status = str(update.get("status", "")).strip()
    if status == "updated":
        return (
            "已自动更新 `clawshelf/clawshelf-brief.md`："
            f"新增 {int(update.get('new_connections', 0))} 个连接，"
            f"本次整理 {int(update.get('candidate_ideas', 0))} 个候选 idea。"
        )
    if status == "unchanged":
        return "已同步 `clawshelf/clawshelf-brief.md`，本次没有新增条目。"
    if status == "failed":
        error = str(update.get("error", "")).strip() or "unknown error"
        return f"自动更新失败：{error}"
    return "自动更新状态不可用。"


def _idea_cards(event: dict) -> list[str]:
    cards: list[str] = []
    for index, idea in enumerate(select_candidate_ideas(event), start=1):
        idea_type = _idea_label(str(idea.get("idea_type", "")))
        relation = str(idea.get("relation", "")).strip() or "evidence-backed connection"
        new_source = _source_label(str(idea.get("new_source_path", "")))
        linked_source = _source_label(str(idea.get("linked_source_path", "")))
        card = [
            f"**{index}. [{idea_type}] {relation}**",
            f"假设：{str(idea.get('connection', '')).strip() or relation}",
            (
                f"新来源：`{new_source or 'unknown'}` "
                f"{str(idea.get('new_evidence', '')).strip()}"
            ).rstrip(),
            (
                f"关联来源：`{linked_source or 'unknown'}` "
                f"{str(idea.get('linked_evidence', '')).strip()}"
            ).rstrip(),
        ]
        if idea.get("total_score") is not None:
            card.append(f"总分：{idea['total_score']}")
        cards.append("\n".join(card))
    return cards


def _source_label(source: str) -> str:
    return source if "://" in source else Path(source).name


def _idea_label(idea_type: str) -> str:
    return {
        "innovation": "创新",
        "consolidation": "巩固",
        "relation_candidate": "关系候选",
        "connection_candidate": "连接候选",
    }.get(idea_type, idea_type or "候选")


def _code_block_items(items: list[str], bullet: bool = False) -> list[str]:
    if not items:
        return ["`unknown`"]
    prefix = "- " if bullet else ""
    return [f"{prefix}`{item}`" for item in items]
