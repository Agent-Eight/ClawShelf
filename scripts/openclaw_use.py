from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clawshelf.auto_normalize import discover_sources, stale_sources
from clawshelf.config import (
    ConfigError,
    DeliveryBinding,
    ShelfConfig,
    load_or_create_config,
    save_config,
)


USE_SCHEMA = "clawshelf.use-result"
WATCH_STATE_SCHEMA = "clawshelf.watch-state"
DEFAULT_COMMANDS_LOG = Path.home() / ".openclaw" / "logs" / "commands.log"
DEFAULT_SESSION_DISCOVERY_MAX_AGE_SECONDS = 15 * 60


@dataclass(frozen=True)
class DeliveryRoute:
    agent_id: str
    channel: str
    session_key: str
    reply_target: str | None = None
    reply_account: str | None = None


def check_readiness(folder: Path) -> dict:
    root = resolve_shelf_root(folder)
    metadata = root / "clawshelf" / "clawshelf-metadata.md"
    normalized = root / "clawshelf" / "normalized"
    normalized_records = sorted(normalized.glob("**/*.md")) if normalized.is_dir() else []
    missing: list[str] = []
    if not (root / "clawshelf").is_dir():
        missing.append("clawshelf/")
    if not normalized.is_dir():
        missing.append("clawshelf/normalized/")
    if not metadata.is_file():
        missing.append("clawshelf/clawshelf-metadata.md")
    status = "ready" if not missing else "partial" if (root / "clawshelf").exists() else "not_onboarded"
    return {
        "status": status,
        "folder": str(root),
        "missing": missing,
        "normalized_records": len(normalized_records),
        "pending_sources": len(stale_sources(root)) if not missing else len(_supported_sources(root)),
    }


def watcher_processes(folder: Path, process_lines: list[str] | None = None) -> list[dict]:
    root = str(resolve_shelf_root(folder))
    lines = process_lines if process_lines is not None else _process_lines()
    matches: list[dict] = []
    for line in lines:
        if "openclaw-watch-adapter.py" not in line and "openclaw_watch_adapter.py" not in line:
            continue
        if root not in line:
            continue
        pid = _line_pid(line)
        if pid == os.getpid():
            continue
        matches.append({"pid": pid, "command": line.strip()})
    return matches


def build_watcher_command(
    folder: Path,
    skill_dir: Path,
    agent_id: str | None = None,
    channel: str = "last",
    session_key: str | None = None,
    reply_target: str | None = None,
    reply_account: str | None = None,
    poll_seconds: float = 5.0,
) -> list[str]:
    if not agent_id or not session_key:
        raise ConfigError(
            "Watcher startup requires the agent and canonical session bound by /clawshelf use."
        )
    command = [
        "uv",
        "run",
        "--locked",
        "--project",
        str(skill_dir),
        "python",
        str(skill_dir / "scripts" / "openclaw-watch-adapter.py"),
        str(folder.resolve()),
        "--poll-seconds",
        _format_seconds(poll_seconds),
        "--channel",
        channel,
        "--agent-id",
        agent_id,
        "--session-key",
        session_key,
    ]
    if reply_target:
        command.extend(["--reply-to", reply_target])
    if reply_account:
        command.extend(["--reply-account", reply_account])
    return command


def start_watcher(
    folder: Path,
    skill_dir: Path,
    agent_id: str | None = None,
    channel: str = "last",
    session_key: str | None = None,
    reply_target: str | None = None,
    reply_account: str | None = None,
    poll_seconds: float = 5.0,
) -> dict:
    root = folder.resolve()
    clawshelf_dir = root / "clawshelf"
    clawshelf_dir.mkdir(parents=True, exist_ok=True)
    log_path = clawshelf_dir / "watch.log"
    command = build_watcher_command(
        root,
        skill_dir,
        agent_id=agent_id,
        channel=channel,
        session_key=session_key,
        reply_target=reply_target,
        reply_account=reply_account,
        poll_seconds=poll_seconds,
    )
    log = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(skill_dir),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    log.close()
    state = {
        "schema": WATCH_STATE_SCHEMA,
        "folder": str(root),
        "pid": process.pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "log_path": str(log_path),
        "channel": channel,
        "delivery_mode": "session_key" if session_key else "channel",
        "adapter": str(skill_dir / "scripts" / "openclaw-watch-adapter.py"),
    }
    state["agent_id"] = agent_id
    state["session_key"] = session_key
    if reply_target:
        state["reply_target"] = reply_target
    if reply_account:
        state["reply_account"] = reply_account
    (clawshelf_dir / "watch-state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def use_folder(
    folder: Path,
    skill_dir: Path,
    agent_id: str | None = None,
    channel: str = "last",
    session_key: str | None = None,
    reply_target: str | None = None,
    reply_account: str | None = None,
    poll_seconds: float = 5.0,
    auto_start: bool = True,
    reset_watcher: bool = True,
    process_lines: list[str] | None = None,
) -> dict:
    root = resolve_shelf_root(folder)
    shelf_plan_prefill = infer_shelf_plan(root)
    config = load_or_create_config(root, _shelf_plan_values(shelf_plan_prefill))
    config = _persist_delivery_binding(
        root,
        config,
        DeliveryRoute(
            agent_id=str(agent_id or ""),
            channel=channel,
            session_key=str(session_key or ""),
            reply_target=reply_target,
            reply_account=reply_account,
        ),
    )
    readiness = check_readiness(root)
    quick_onboard = {
        "needed": readiness["status"] != "ready",
        "performed": False,
        "mode": "quick",
        "ask_policy": "persisted_auto_accept",
        "requires_confirmation": False,
        "shelf_plan_prefill": _prefill_from_config(config),
        "processed": 0,
        "skipped": 0,
        "warnings": [],
    }
    if readiness["status"] != "ready":
        quick_onboard.update(run_quick_onboard(root))
        readiness = check_readiness(root)

    watcher = ensure_watcher(
        root,
        skill_dir,
        agent_id=agent_id,
        channel=channel,
        session_key=session_key,
        reply_target=reply_target,
        reply_account=reply_account,
        poll_seconds=poll_seconds,
        auto_start=auto_start,
        reset_watcher=reset_watcher,
        process_lines=process_lines,
    )
    next_action = _next_action(readiness["status"])
    return {
        "schema": USE_SCHEMA,
        "folder": str(root),
        "requested_folder": str(folder.resolve()),
        "readiness": readiness,
        "next_action": next_action,
        "quick_onboard": quick_onboard,
        "config": config.to_dict(),
        "config_fingerprint": config.fingerprint,
        "watcher": watcher,
    }


def reset_folder_watcher(
    folder: Path,
    skill_dir: Path,
    agent_id: str | None = None,
    channel: str = "last",
    session_key: str | None = None,
    reply_target: str | None = None,
    reply_account: str | None = None,
    poll_seconds: float = 5.0,
    process_lines: list[str] | None = None,
) -> dict:
    root = resolve_shelf_root(folder)
    config = load_or_create_config(root, _shelf_plan_values(infer_shelf_plan(root)))
    readiness = check_readiness(root)
    watcher = ensure_watcher(
        root,
        skill_dir,
        agent_id=agent_id,
        channel=channel,
        session_key=session_key,
        reply_target=reply_target,
        reply_account=reply_account,
        poll_seconds=poll_seconds,
        auto_start=readiness["status"] == "ready",
        reset_watcher=True,
        process_lines=process_lines,
    )
    return {
        "schema": USE_SCHEMA,
        "folder": str(root),
        "requested_folder": str(folder.resolve()),
        "readiness": readiness,
        "next_action": _next_action(readiness["status"]),
        "quick_onboard": {
            "needed": False,
            "performed": False,
            "mode": "none",
            "ask_policy": "not_applicable",
            "requires_confirmation": False,
            "shelf_plan_prefill": infer_shelf_plan(root),
            "processed": 0,
            "skipped": 0,
            "warnings": [],
        },
        "config": config.to_dict(),
        "config_fingerprint": config.fingerprint,
        "watcher": watcher,
    }


def run_quick_onboard(folder: Path) -> dict:
    root = folder.resolve()
    config = load_or_create_config(root, _shelf_plan_values(infer_shelf_plan(root)))
    sources = _supported_sources(root)
    clawshelf = root / "clawshelf"
    normalized = clawshelf / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    metadata = clawshelf / "clawshelf-metadata.md"
    if not metadata.is_file():
        metadata.write_text(
            "# ClawShelf Metadata - Auto-normalized watcher shelf\n\n"
            f"- Collection: `{root}`\n"
            "- Documents: 0\n"
            "- Status: watcher will reconcile pending sources.\n",
            encoding="utf-8",
        )
    return {
        "needed": True,
        "performed": True,
        "mode": "quick",
        "ask_policy": "persisted_auto_accept",
        "requires_confirmation": False,
        "shelf_plan_prefill": _prefill_from_config(config),
        "processed": 0,
        "skipped": len(sources),
        "warnings": [f"{len(sources)} source(s) queued for watcher reconciliation."] if sources else [],
    }


def infer_shelf_plan(folder: Path) -> dict:
    root = resolve_shelf_root(folder)
    supported = _supported_sources(root)
    text = " ".join([root.name, *(path.name for path in supported)]).lower()
    domain, domain_evidence = _infer_domain(text, supported)
    work_direction, direction_evidence = _infer_direction(text)
    concrete_problem, problem_evidence = _infer_problem(text)
    collection_pattern, pattern_evidence = _infer_pattern(supported)
    companion_mode, companion_evidence = _companion_for_domain(domain)
    return {
        "schema": "clawshelf.shelf-plan-prefill",
        "requires_confirmation": True,
        "fields": {
            "domain_background": _prefill(domain, domain_evidence),
            "work_direction": _prefill(work_direction, direction_evidence),
            "concrete_problem": _prefill(concrete_problem, problem_evidence),
            "collection_pattern": _prefill(collection_pattern, pattern_evidence),
            "companion_mode": _prefill(companion_mode, companion_evidence),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Use a ClawShelf folder and ensure its OpenClaw watcher is running.")
    parser.add_argument("folder", help="Local ClawShelf working folder.")
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]), help="ClawShelf skill directory.")
    parser.add_argument("--agent-id", default=os.environ.get("OPENCLAW_AGENT_ID"), help="Runtime OpenClaw agent for delivery turns.")
    parser.add_argument("--channel", default=os.environ.get("CLAWSHELF_DELIVERY_CHANNEL", "last"), help="OpenClaw delivery channel abstraction.")
    parser.add_argument("--session-key", default=None, help="OpenClaw session key to bind watcher delivery.")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="Watcher fallback polling interval.")
    parser.add_argument("--no-start", action="store_true", help="Only check watcher state; do not auto-start.")
    parser.add_argument("--reset-only", action="store_true", help="Only reset the watcher for a ready shelf; do not onboard or repair.")
    reset_group = parser.add_mutually_exclusive_group()
    reset_group.add_argument("--reset", dest="reset_watcher", action="store_true", help="Restart any existing watcher before starting a fresh one.")
    reset_group.add_argument("--no-reset", dest="reset_watcher", action="store_false", help="Keep an existing watcher when one is already running.")
    parser.set_defaults(reset_watcher=True)
    args = parser.parse_args(argv)
    skill_dir = Path(args.skill_dir).resolve()
    try:
        root = resolve_shelf_root(Path(args.folder))
        persisted = load_or_create_config(
            root,
            _shelf_plan_values(infer_shelf_plan(root)),
        ).delivery_binding
        if args.reset_only and persisted:
            route = _route_from_binding(persisted)
        else:
            route = resolve_delivery_route(
                args.session_key or os.environ.get("OPENCLAW_SESSION_KEY"),
                agent_id=args.agent_id,
                channel=args.channel,
            )
        if args.reset_only:
            result = reset_folder_watcher(
                Path(args.folder),
                skill_dir,
                agent_id=route.agent_id,
                channel=route.channel,
                session_key=route.session_key,
                reply_target=route.reply_target,
                reply_account=route.reply_account,
                poll_seconds=args.poll_seconds,
            )
        else:
            result = use_folder(
                Path(args.folder),
                skill_dir,
                agent_id=route.agent_id,
                channel=route.channel,
                session_key=route.session_key,
                reply_target=route.reply_target,
                reply_account=route.reply_account,
                poll_seconds=args.poll_seconds,
                auto_start=not args.no_start,
                reset_watcher=args.reset_watcher,
            )
    except ConfigError as exc:
        print(json.dumps({"status": "config_invalid", "error": str(exc), "folder": str(Path(args.folder).resolve())}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["readiness"]["status"] == "ready" else 3


def resolve_delivery_route(
    explicit_session_key: str | None = None,
    *,
    agent_id: str | None = None,
    channel: str = "last",
    commands_log: Path | None = None,
    now: datetime | None = None,
    max_age_seconds: float | None = None,
) -> DeliveryRoute:
    """Bind a watcher to the concrete channel and session that invoked use.

    Slash commands are recorded by OpenClaw's command-logger hook with the
    exact session key and source channel. The shell process itself does not
    receive those values, so ``channel=last`` is resolved once from the newest
    matching command and is never persisted as a runtime delivery route.
    """
    requested_channel = str(channel or "last").strip().lower()
    explicit = str(explicit_session_key or "").strip() or None
    log_path = commands_log or Path(os.environ.get("OPENCLAW_COMMANDS_LOG", DEFAULT_COMMANDS_LOG))
    try:
        entries = log_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        entries = []

    current = now or datetime.now(timezone.utc)
    age_limit = max_age_seconds
    if age_limit is None:
        raw_limit = os.environ.get("OPENCLAW_SESSION_DISCOVERY_MAX_AGE_SECONDS")
        try:
            age_limit = float(raw_limit) if raw_limit else DEFAULT_SESSION_DISCOVERY_MAX_AGE_SECONDS
        except ValueError:
            age_limit = DEFAULT_SESSION_DISCOVERY_MAX_AGE_SECONDS
    minimum_time = current - timedelta(seconds=max(0.0, age_limit))
    expected_channel = requested_channel if requested_channel != "last" else None
    candidates: list[tuple[datetime, str, str, str, str]] = []
    for line in reversed(entries):
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        session_key = entry.get("sessionKey")
        timestamp = entry.get("timestamp")
        source = str(entry.get("source") or "").strip().lower()
        sender_id = str(entry.get("senderId") or "").strip()
        account_id = str(entry.get("accountId") or "").strip()
        if not isinstance(session_key, str) or not session_key.strip() or not isinstance(timestamp, str):
            continue
        try:
            session_agent = _agent_from_session_key(session_key)
        except ConfigError:
            continue
        if agent_id and session_agent != agent_id:
            continue
        if expected_channel and source != expected_channel:
            continue
        try:
            recorded_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if recorded_at > current or recorded_at < minimum_time:
            continue
        candidates.append((recorded_at, session_key.strip(), source, sender_id, account_id))

    if explicit:
        explicit_agent = _agent_from_session_key(explicit)
        if agent_id and explicit_agent != agent_id:
            raise ConfigError(
                f"Explicit agent {agent_id!r} does not match session agent {explicit_agent!r}."
            )
        matching = [item for item in candidates if item[1] == explicit]
        newest = max(matching, key=lambda item: item[0]) if matching else None
        return _delivery_route(
            explicit,
            requested_channel,
            source=newest[2] if newest else "",
            sender_id=newest[3] if newest else "",
            account_id=newest[4] if newest else "",
        )

    if candidates:
        newest = max(candidates, key=lambda item: item[0])
        return _delivery_route(
            newest[1],
            requested_channel,
            source=newest[2],
            sender_id=newest[3],
            account_id=newest[4],
        )
    raise ConfigError(
        "Cannot resolve the invoking OpenClaw agent/channel/session from a recent "
        "/clawshelf use command. Run the command from the target conversation and "
        "pass its canonical session key."
    )


def _delivery_route(
    session_key: str,
    requested_channel: str,
    *,
    source: str = "",
    sender_id: str = "",
    account_id: str = "",
) -> DeliveryRoute:
    agent_id = _agent_from_session_key(session_key)
    session_channel = _channel_from_session_key(session_key)
    channel = session_channel if requested_channel == "last" else requested_channel
    if source and channel != source:
        raise ConfigError(
            f"Explicit channel {channel!r} does not match session channel {source!r}."
        )
    if session_channel and channel != session_channel:
        raise ConfigError(
            f"Explicit channel {channel!r} does not match canonical session channel "
            f"{session_channel!r}."
        )
    reply_target = _reply_target(channel, sender_id, session_key)
    reply_account = account_id or (agent_id if channel == "feishu" else None)
    return DeliveryRoute(
        agent_id=agent_id,
        channel=channel,
        session_key=session_key,
        reply_target=reply_target,
        reply_account=reply_account,
    )


def _agent_from_session_key(session_key: str) -> str:
    parts = [item.strip() for item in str(session_key).split(":")]
    if len(parts) < 4 or parts[0] != "agent" or not parts[1]:
        raise ConfigError(
            "A canonical OpenClaw session key in the form agent:<agent-id>:<channel>:... "
            "is required."
        )
    return parts[1]


def _channel_from_session_key(session_key: str) -> str:
    parts = [item.strip().lower() for item in str(session_key).split(":")]
    if len(parts) < 4 or not parts[2]:
        raise ConfigError("Canonical session key is missing its channel.")
    return parts[2]


def _reply_target(channel: str, sender_id: str, session_key: str) -> str | None:
    if channel != "feishu":
        return None
    open_id = sender_id.strip()
    if not open_id:
        open_id = next(
            (part for part in reversed(session_key.split(":")) if part.startswith("ou_")),
            "",
        )
    return f"user:{open_id}" if open_id else None


def _persist_delivery_binding(
    folder: Path,
    config: ShelfConfig,
    route: DeliveryRoute,
) -> ShelfConfig:
    if not route.agent_id or not route.session_key:
        raise ConfigError(
            "Cannot persist delivery_binding without the initial agent and canonical session."
        )
    binding = DeliveryBinding(
        agent=route.agent_id,
        session=route.session_key,
        channel=route.channel,
        target=route.reply_target or "",
        account=route.reply_account or "",
    )
    if config.delivery_binding == binding:
        return config
    updated = replace(config, delivery_binding=binding)
    save_config(folder, updated)
    return updated


def _route_from_binding(binding: DeliveryBinding) -> DeliveryRoute:
    return DeliveryRoute(
        agent_id=binding.agent,
        channel=binding.channel,
        session_key=binding.session,
        reply_target=binding.target or None,
        reply_account=binding.account or None,
    )


def resolve_shelf_root(folder: Path) -> Path:
    root = folder.resolve()
    if root.name == "clawshelf" and (root / "normalized").is_dir() and (root / "clawshelf-metadata.md").is_file():
        return root.parent.resolve()
    return root


def ensure_watcher(
    folder: Path,
    skill_dir: Path,
    agent_id: str | None = None,
    channel: str = "last",
    session_key: str | None = None,
    reply_target: str | None = None,
    reply_account: str | None = None,
    poll_seconds: float = 5.0,
    auto_start: bool = True,
    reset_watcher: bool = True,
    process_lines: list[str] | None = None,
) -> dict:
    root = resolve_shelf_root(folder)
    readiness = check_readiness(root)
    processes = watcher_processes(root, process_lines)
    state = _watch_state(root)
    stale_state = _stale_watch_state(state, root, processes)
    started = None
    stop_result = {"stopped_processes": [], "errors": []}
    reset_attempted = False
    if auto_start and readiness["status"] == "ready":
        if reset_watcher:
            reset_attempted = True
            stop_result = stop_watcher(root, process_lines=process_lines)
            if not stop_result["errors"]:
                _clear_watch_state(root)
                processes = []
                state = {}
                started = start_watcher(
                    root,
                    skill_dir,
                    agent_id=agent_id,
                    channel=channel,
                    session_key=session_key,
                    reply_target=reply_target,
                    reply_account=reply_account,
                    poll_seconds=poll_seconds,
                )
        elif not processes:
            started = start_watcher(
                root,
                skill_dir,
                agent_id=agent_id,
                channel=channel,
                session_key=session_key,
                reply_target=reply_target,
                reply_account=reply_account,
                poll_seconds=poll_seconds,
            )
        if started:
            processes = [
                {
                    "pid": started["pid"],
                    "command": " ".join(
                        build_watcher_command(
                            root,
                            skill_dir,
                            agent_id=agent_id,
                            channel=channel,
                            session_key=session_key,
                            reply_target=reply_target,
                            reply_account=reply_account,
                            poll_seconds=poll_seconds,
                        )
                    ),
                }
            ]
            state = started
    status = "running" if processes else "missing"
    if stop_result["errors"]:
        status = "reset_failed"
    elif stale_state and started:
        status = "restarted"
    elif reset_attempted and started and stop_result["stopped_processes"]:
        status = "restarted"
    elif reset_attempted and started:
        status = "reset_started"
    elif stale_state:
        status = "stale"
    return {
        "exists": bool(processes),
        "status": status,
        "auto_started": started is not None,
        "reset": reset_attempted,
        "stopped_processes": stop_result["stopped_processes"],
        "stop_errors": stop_result["errors"],
        "stale_state": stale_state,
        "processes": processes,
        "state": state if isinstance(state, dict) else {},
        "watched_root": str(root),
        "event_dir": str(root / "clawshelf" / "events"),
    }


def stop_watcher(folder: Path, process_lines: list[str] | None = None, timeout_seconds: float = 1.5) -> dict:
    root = resolve_shelf_root(folder)
    matches = watcher_processes(root, process_lines)
    stopped: list[dict] = []
    errors: list[str] = []
    for process in matches:
        pid = int(process.get("pid") or 0)
        if pid <= 0 or pid == os.getpid():
            errors.append(f"invalid watcher pid for {root}: {pid}")
            continue
        if process_lines is not None:
            stopped.append(process)
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(0.05)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
            stopped.append(process)
        except ProcessLookupError:
            stopped.append(process)
        except OSError as exc:
            errors.append(f"failed to stop watcher pid {pid}: {exc}")
    if stopped and not errors:
        _clear_watch_state(root)
    return {"stopped_processes": stopped, "errors": errors}


def _supported_sources(folder: Path) -> list[Path]:
    return discover_sources(folder)


def _prefill(value: str, evidence: str, confidence: str = "medium") -> dict:
    return {
        "value": value,
        "confidence": confidence,
        "evidence": evidence,
        "confirmed": False,
    }


def _shelf_plan_values(prefill: dict) -> dict[str, str]:
    return {field: str(value["value"]) for field, value in prefill.get("fields", {}).items()}


def _prefill_from_config(config: ShelfConfig) -> dict:
    return {
        "schema": "clawshelf.shelf-plan-prefill",
        "requires_confirmation": False,
        "fields": {
            key: {"value": value, "confidence": "persisted", "evidence": "clawshelf/clawshelf-config.json", "confirmed": True}
            for key, value in config.shelf_plan.items()
        },
    }


def _infer_domain(text: str, sources: list[Path]) -> tuple[str, str]:
    if _has_any(text, {"trading", "market", "markets", "portfolio", "liquidity", "retail", "prediction", "quant", "finance", "factor"}):
        return "financial/investment research", "matched finance/trading terms in folder or filenames"
    if _has_any(text, {"product", "market-report", "customer", "competitor", "roadmap"}):
        return "industrial/product research", "matched product or market-research terms in folder or filenames"
    if _has_any(text, {"engineering", "architecture", "benchmark", "design", "system", "api"}):
        return "engineering R&D", "matched engineering terms in folder or filenames"
    if _has_any(text, {"draft", "essay", "chapter", "writing", "outline", "notes"}):
        return "writing/knowledge work", "matched writing or notes terms in folder or filenames"
    if any(path.suffix.lower() == ".pdf" for path in sources):
        return "basic science", "PDF-heavy shelf suggests paper/literature review"
    return "unknown", "no strong domain signal found"


def _infer_direction(text: str) -> tuple[str, str]:
    if _has_any(text, {"idea", "signal", "alpha", "edge", "prediction"}):
        return "idea discovery", "matched idea/signal terms in folder or filenames"
    if _has_any(text, {"experiment", "design", "benchmark", "execution"}):
        return "experiment/design tracking", "matched experiment/design terms in folder or filenames"
    if _has_any(text, {"report", "writing", "brief", "memo"}):
        return "report writing", "matched report/writing terms in folder or filenames"
    return "literature review", "default for a document shelf of source papers"


def _infer_problem(text: str) -> tuple[str, str]:
    if _has_any(text, {"contradiction", "versus", "compare", "competition"}):
        return "compare competing views", "matched comparison terms in folder or filenames"
    if _has_any(text, {"risk", "gap", "crowding", "liquidity"}):
        return "identify gaps/risks", "matched risk/gap terms in folder or filenames"
    if _has_any(text, {"idea", "signal", "edge", "prediction"}):
        return "find new research directions", "matched idea/signal terms in folder or filenames"
    return "organize and cite sources", "default first problem for a new source shelf"


def _infer_pattern(sources: list[Path]) -> tuple[str, str]:
    if len(sources) >= 10:
        return "steadily growing shelf", f"{len(sources)} supported source files found"
    if len(sources) >= 2:
        return "project-by-project archive", f"{len(sources)} supported source files found"
    return "one-time batch", f"{len(sources)} supported source file found"


def _companion_for_domain(domain: str) -> tuple[str, str]:
    mapping = {
        "financial/investment research": "investment research assistant",
        "industrial/product research": "product secretary",
        "engineering R&D": "engineering knowledge assistant",
        "writing/knowledge work": "writing assistant",
        "basic science": "research secretary",
    }
    if domain in mapping:
        return mapping[domain], f"derived from domain_background: {domain}"
    return "research secretary", "default companion mode for unknown domain"


def _has_any(text: str, needles: set[str]) -> bool:
    return any(needle in text for needle in needles)


def _process_lines() -> list[str]:
    completed = subprocess.run(["ps", "-axo", "pid,command"], text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def _watch_state(folder: Path) -> dict:
    path = resolve_shelf_root(folder) / "clawshelf" / "watch-state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _clear_watch_state(folder: Path) -> None:
    path = resolve_shelf_root(folder) / "clawshelf" / "watch-state.json"
    path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stale_watch_state(state: dict, folder: Path, processes: list[dict]) -> bool:
    if not state:
        return False
    root = str(resolve_shelf_root(folder))
    if state.get("folder") != root:
        return True
    pid = _state_pid(state)
    if not pid:
        return True
    return not any(process.get("pid") == pid for process in processes)


def _state_pid(state: dict) -> int:
    try:
        return int(state.get("pid", 0))
    except (TypeError, ValueError):
        return 0


def _line_pid(line: str) -> int:
    first = line.strip().split(maxsplit=1)[0]
    try:
        return int(first)
    except ValueError:
        return 0


def _format_seconds(seconds: float) -> str:
    value = float(seconds)
    return str(int(value)) if value.is_integer() else str(value)


def _next_action(status: str) -> str:
    if status == "ready":
        return "ask_or_refresh"
    if status == "not_onboarded":
        return "quick_onboard"
    if status == "partial":
        return "repair"
    return "status"


if __name__ == "__main__":
    raise SystemExit(main())
