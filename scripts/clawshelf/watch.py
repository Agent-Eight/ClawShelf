from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from typing import Callable

from .auto_normalize import normalize_sources, stale_sources
from .brief import failed_brief_update, update_synthesis_brief
from .events import CreativityScoringOptions, NormalizationOutcome, classify_new_files, write_event
from .keyword_worker import KeywordWorker
from .config import ConfigError, ShelfConfig, effective_config, load_or_create_config
from .normalize import parse_normalized_record
from .semantic_retrieval import qmd_semantic_retriever


IGNORED_DIRS = {".git", ".hg", ".svn", ".venv", "__pycache__", "clawshelf"}
IGNORED_SUFFIXES = {".tmp", ".part", ".download", ".crdownload", ".swp", ".pyc"}
STARTUP_RECONCILE_LIMIT = 25


@dataclass(frozen=True)
class FileSnapshot:
    size: int
    mtime_ns: int


WatchResult = tuple[Path, dict] | None
ResultEmitter = Callable[[WatchResult], None]


def should_ignore(path: Path, folder: Path) -> bool:
    try:
        relative = path.resolve().relative_to(folder.resolve())
    except ValueError:
        return True
    if any(part in IGNORED_DIRS for part in relative.parts):
        return True
    name = path.name
    if name.startswith(".") or name.endswith("~"):
        return True
    return path.suffix.lower() in IGNORED_SUFFIXES


def stable_files(paths: list[Path], interval_seconds: float = 0.5) -> list[Path]:
    if not paths:
        return []
    before = {path.resolve(): _snapshot(path) for path in paths}
    time.sleep(interval_seconds)
    return [
        path
        for path, snapshot in before.items()
        if snapshot is not None and _snapshot(path) == snapshot
    ]


def handle_files(
    folder: Path,
    files: list[Path],
    refresh_command: str | None = None,
    push_target: str = "host_decides",
    creativity_options: CreativityScoringOptions | None = None,
    keyword_worker: KeywordWorker | None = None,
    keyword_model: str | None = None,
    config: ShelfConfig | None = None,
) -> WatchResult:
    root = folder.resolve()
    config = config or load_or_create_config(root)
    candidates = sorted({path.resolve() for path in files if path.is_file() and not should_ignore(path, root)})
    stable = stable_files(candidates)
    if not stable:
        return None
    normalize_results = normalize_sources(root, stable, keyword_worker=keyword_worker, keyword_model=keyword_model, config=config)
    normalization_warnings = [
        f"{result.source.name}: {warning}"
        for result in normalize_results
        for warning in result.warnings
        if result.status != "current"
    ]
    normalization_outcomes = [
        NormalizationOutcome(
            source=str(result.source.resolve()),
            status=result.status,
            record_path=str(getattr(result, "record_path", None).resolve()) if getattr(result, "record_path", None) else "",
            coverage=getattr(result, "coverage", "none"),
            warnings=list(result.warnings),
            key_arguments=_normalized_key_arguments(
                getattr(result, "record_path", None)
            ),
        )
        for result in normalize_results
    ]
    if refresh_command:
        refresh_warning = _run_refresh_command(refresh_command, root, stable)
        if refresh_warning:
            normalization_warnings.append(refresh_warning)
    event = classify_new_files(
        root,
        stable,
        push_target=push_target,
        creativity_options=creativity_options,
        normalization_warnings=normalization_warnings,
        normalization_outcomes=normalization_outcomes,
        config=config,
    )
    if event.priority == "P1":
        try:
            brief_update = update_synthesis_brief(
                root,
                event.to_dict(),
                config,
            )
        except Exception as exc:
            brief_update = failed_brief_update(root, exc)
        event.synthesis_brief_update = brief_update.to_dict()
    event_path = write_event(root, event)
    return event_path, event.to_dict()


def _normalized_key_arguments(record_path: Path | None, limit: int = 5) -> list[str]:
    if not record_path or not record_path.is_file():
        return []
    try:
        record = parse_normalized_record(
            record_path.read_text(encoding="utf-8", errors="replace")
        )
    except (OSError, ValueError):
        return []
    arguments: list[str] = []
    for line in record.sections.get("Key Claims", "").splitlines():
        value = line.strip()
        if not value.startswith("- "):
            continue
        argument = value[2:].strip()
        if argument:
            arguments.append(argument)
        if len(arguments) >= limit:
            break
    return arguments


def watch_folder(
    folder: Path,
    refresh_command: str | None = None,
    poll_seconds: float = 2.0,
    push_target: str = "host_decides",
    emit_result: ResultEmitter | None = None,
    creativity_options: CreativityScoringOptions | None = None,
    keyword_worker: KeywordWorker | None = None,
    keyword_model: str | None = None,
    config: ShelfConfig | None = None,
) -> int:
    root = folder.resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    emit = emit_result or _print_event
    config = config or load_or_create_config(root)
    _log_watch_lifecycle(root, "starting")
    _reconcile_startup(root, refresh_command, push_target, emit, creativity_options, keyword_worker, keyword_model, config)
    try:
        from watchfiles import Change, watch
    except ImportError:
        _log_watch_lifecycle(root, "ready", backend="polling")
        return _poll_folder(root, refresh_command, poll_seconds, push_target, emit, creativity_options, keyword_worker, keyword_model, config)

    print(f"Watching {root}")
    _log_watch_lifecycle(root, "ready", backend="watchfiles")
    try:
        for changes in watch(root):
            paths = [Path(path) for change, path in changes if change in (Change.added, Change.modified)]
            try:
                emit(handle_files(root, paths, refresh_command, push_target, creativity_options, keyword_worker, keyword_model, config))
            except Exception as exc:
                _log_watch_error(root, exc)
    except Exception as exc:
        _log_watch_lifecycle(
            root,
            "unexpected_exit",
            error_type=type(exc).__name__,
            message=str(exc),
        )
        return 1
    _log_watch_lifecycle(root, "stopped")
    return 0


def _reconcile_startup(
    folder: Path,
    refresh_command: str | None,
    push_target: str,
    emit: ResultEmitter,
    creativity_options: CreativityScoringOptions | None,
    keyword_worker: KeywordWorker | None,
    keyword_model: str | None,
    config: ShelfConfig | None = None,
) -> None:
    config = config or load_or_create_config(folder)
    pending = stale_sources(folder, config)[:STARTUP_RECONCILE_LIMIT]
    if not pending:
        return
    try:
        emit(
            handle_files(
                folder,
                pending,
                refresh_command,
                push_target,
                creativity_options,
                keyword_worker,
                keyword_model,
                config,
            )
        )
    except Exception as exc:
        _log_watch_error(folder, exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch a ClawShelf folder and emit P1/P2 intake events.")
    parser.add_argument("folder", help="Local ClawShelf working folder to watch.")
    parser.add_argument(
        "--refresh-command",
        help="Optional host command to run before classification. Supports {folder} and {paths}.",
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Fallback polling interval.")
    parser.add_argument("--once", nargs="*", help="Process specific files once instead of watching.")
    parser.add_argument("--creativity-scorer", choices=["auto", "off", "required"], help="Creativity scorer mode.")
    parser.add_argument("--creativity-model", help="Host model alias for creativity scoring.")
    parser.add_argument("--creativity-threshold", type=int, help="Creativity P1 threshold.")
    parser.add_argument("--creativity-min-confidence", type=float, help="Minimum creativity P1 confidence.")
    parser.add_argument("--candidate-limit", type=int, help="Maximum candidates sent to creativity scoring.")
    parser.add_argument("--novelty-preference", type=float, help="0 favors overlap; 1 favors evidence-backed novelty.")
    parser.add_argument(
        "--semantic-retrieval",
        choices=["auto", "off", "required"],
        help="Use QMD vector search only to fill the candidate set.",
    )
    parser.add_argument(
        "--semantic-candidate-target",
        type=int,
        help="Fill deterministic candidates up to this target with QMD vector hits.",
    )
    parser.add_argument(
        "--qmd-bin",
        default=os.environ.get("QMD_BIN", "qmd"),
        help="QMD CLI binary.",
    )
    args = parser.parse_args(argv)

    folder = Path(args.folder).resolve()
    try:
        config = effective_config(load_or_create_config(folder), args)
    except (ConfigError, ValueError) as exc:
        parser.error(str(exc))
    creativity_options = creativity_options_from_config(folder, args, config)
    if args.once is not None:
        files = [Path(path) for path in args.once]
        _print_event(handle_files(folder, files, args.refresh_command, creativity_options=creativity_options, config=config))
        return 0
    return watch_folder(folder, args.refresh_command, args.poll_seconds, creativity_options=creativity_options, config=config)


def creativity_options_from_config(folder: Path, args: argparse.Namespace, config: ShelfConfig | None = None) -> CreativityScoringOptions:
    config = config or effective_config(load_or_create_config(folder), args)
    creativity = config.creativity_scoring
    return CreativityScoringOptions(
        mode=creativity.mode,
        model=creativity.model,
        creativity_threshold=creativity.advanced.threshold,
        min_confidence=creativity.advanced.min_confidence,
        candidate_limit=creativity.candidate_limit,
        novelty_preference=creativity.novelty_preference,
        semantic_retrieval=creativity.semantic_retrieval,
        semantic_candidate_target=creativity.semantic_candidate_target,
        shelf_plan=config.shelf_plan,
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


def _snapshot(path: Path) -> FileSnapshot | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return FileSnapshot(stat.st_size, stat.st_mtime_ns)


def _run_refresh_command(command: str, folder: Path, files: list[Path]) -> str:
    try:
        rendered = command.format(folder=str(folder), paths=" ".join(str(path) for path in files))
        completed = subprocess.run(shlex.split(rendered), check=False, timeout=120)
    except (KeyError, IndexError, OSError, subprocess.TimeoutExpired) as exc:
        return f"refresh command failed: {exc}"
    if completed.returncode != 0:
        return f"refresh command failed with exit code {completed.returncode}"
    return ""


def _poll_folder(
    folder: Path,
    refresh_command: str | None,
    poll_seconds: float,
    push_target: str,
    emit_result: ResultEmitter,
    creativity_options: CreativityScoringOptions | None = None,
    keyword_worker: KeywordWorker | None = None,
    keyword_model: str | None = None,
    config: ShelfConfig | None = None,
) -> int:
    print(f"watchfiles unavailable; polling {folder} every {poll_seconds:g}s")
    seen = _current_snapshots(folder)
    while True:
        time.sleep(poll_seconds)
        current = _current_snapshots(folder)
        changed = [path for path, snapshot in current.items() if seen.get(path) != snapshot]
        seen = current
        try:
            emit_result(handle_files(folder, changed, refresh_command, push_target, creativity_options, keyword_worker, keyword_model, config))
        except Exception as exc:
            _log_watch_error(folder, exc)


def _log_watch_error(folder: Path, exc: Exception) -> None:
    payload = {
        "level": "error",
        "component": "watch_loop",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    _append_watch_log(folder, payload)


def _log_watch_lifecycle(
    folder: Path,
    event: str,
    **details: str,
) -> None:
    payload = {
        "level": "info" if event != "unexpected_exit" else "error",
        "component": "watcher_lifecycle",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **details,
    }
    _append_watch_log(folder, payload)


def _append_watch_log(folder: Path, payload: dict) -> None:
    log_path = folder.resolve() / "clawshelf" / "watch.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def _current_snapshots(folder: Path) -> dict[Path, FileSnapshot]:
    snapshots: dict[Path, FileSnapshot] = {}
    for path in folder.rglob("*"):
        if path.is_file() and not should_ignore(path, folder):
            snapshot = _snapshot(path)
            if snapshot:
                snapshots[path.resolve()] = snapshot
    return snapshots


def _print_event(result: tuple[Path, dict] | None) -> None:
    if not result:
        return
    path, event = result
    print(json.dumps({"event_path": str(path), **event}, ensure_ascii=False))
