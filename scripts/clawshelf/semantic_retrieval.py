from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Protocol

from .normalize import NormalizedRecord
from .terms import semantic_query_text


class SemanticRetrievalError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticHit:
    path: str
    similarity: float


@dataclass(frozen=True)
class SemanticRetrievalResult:
    backend: str = "qmd_vector"
    status: str = "not_used"
    hits: list[SemanticHit] = field(default_factory=list)
    error: str = ""


class SemanticRetriever(Protocol):
    def __call__(
        self,
        new_record_path: Path,
        new_record: NormalizedRecord,
        records: list[tuple[Path, NormalizedRecord]],
        limit: int,
    ) -> SemanticRetrievalResult:
        ...


def qmd_semantic_retriever(
    folder: Path,
    *,
    qmd_bin: str = "qmd",
    timeout_seconds: int = 240,
) -> SemanticRetriever:
    root = folder.resolve()
    prepared_signature: tuple[tuple[str, int, int], ...] | None = None

    def retrieve(
        new_record_path: Path,
        new_record: NormalizedRecord,
        records: list[tuple[Path, NormalizedRecord]],
        limit: int,
    ) -> SemanticRetrievalResult:
        nonlocal prepared_signature
        signature = _normalized_signature(root / "clawshelf" / "normalized")
        result = run_qmd_vector_retrieval(
            root,
            new_record_path,
            new_record,
            records,
            limit,
            qmd_bin=qmd_bin,
            timeout_seconds=timeout_seconds,
            prepare_index=signature != prepared_signature,
        )
        if result.status != "unavailable":
            prepared_signature = signature
        return result

    return retrieve


def run_qmd_vector_retrieval(
    folder: Path,
    new_record_path: Path,
    new_record: NormalizedRecord,
    records: list[tuple[Path, NormalizedRecord]],
    limit: int,
    *,
    qmd_bin: str = "qmd",
    timeout_seconds: int = 240,
    prepare_index: bool = True,
) -> SemanticRetrievalResult:
    if limit <= 0:
        return SemanticRetrievalResult(status="not_needed")
    if not shutil.which(qmd_bin):
        return SemanticRetrievalResult(
            status="unavailable",
            error=f"QMD binary not found: {qmd_bin}",
        )
    normalized_dir = folder.resolve() / "clawshelf" / "normalized"
    collection = collection_name(folder)
    try:
        if prepare_index:
            _ensure_collection(qmd_bin, normalized_dir, collection, timeout_seconds)
        completed = _run(
            [
                qmd_bin,
                "vsearch",
                semantic_query_text(new_record),
                "-c",
                collection,
                "--format",
                "json",
                "--full-path",
                "-n",
                str(limit + 1),
            ],
            timeout_seconds,
        )
        if completed.returncode != 0:
            raise SemanticRetrievalError(_command_error(completed))
        allowed = {str(path.resolve()): path.resolve() for path, _ in records}
        self_path = new_record_path.resolve()
        hits: list[SemanticHit] = []
        for path_value, score in parse_qmd_results(completed.stdout):
            resolved = _resolve_result_path(path_value, normalized_dir, allowed)
            if not resolved or resolved == self_path or str(resolved) not in allowed:
                continue
            hits.append(SemanticHit(str(resolved), score))
            if len(hits) >= limit:
                break
        return SemanticRetrievalResult(status="used", hits=hits)
    except (OSError, subprocess.TimeoutExpired, SemanticRetrievalError) as exc:
        return SemanticRetrievalResult(status="unavailable", error=str(exc))


def collection_name(folder: Path) -> str:
    digest = hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"clawshelf-{digest}"


def parse_qmd_results(text: str) -> list[tuple[str, float]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SemanticRetrievalError("QMD vector search returned invalid JSON") from exc
    rows = payload if isinstance(payload, list) else next(
        (
            payload.get(key)
            for key in ("results", "hits", "items")
            if isinstance(payload.get(key), list)
        ),
        [],
    )
    parsed: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = next(
            (
                str(row.get(key)).strip()
                for key in ("path", "file", "filename", "source", "docid")
                if row.get(key)
            ),
            "",
        )
        if not path:
            continue
        score_value = next(
            (
                row.get(key)
                for key in ("score", "similarity", "vector_score")
                if row.get(key) is not None
            ),
            0.0,
        )
        try:
            score = float(score_value)
        except (TypeError, ValueError):
            score = 0.0
        parsed.append((path, score))
    return parsed


def _ensure_collection(
    qmd_bin: str,
    normalized_dir: Path,
    collection: str,
    timeout_seconds: int,
) -> None:
    show = _run([qmd_bin, "collection", "show", collection], timeout_seconds)
    if show.returncode != 0:
        added = _run(
            [
                qmd_bin,
                "collection",
                "add",
                str(normalized_dir),
                "--name",
                collection,
            ],
            timeout_seconds,
        )
        if added.returncode != 0 and "already exists" not in _command_error(added).lower():
            raise SemanticRetrievalError(_command_error(added))
    updated = _run([qmd_bin, "update"], timeout_seconds)
    if updated.returncode != 0:
        raise SemanticRetrievalError(_command_error(updated))
    embedded = _run([qmd_bin, "embed", "-c", collection], timeout_seconds)
    if embedded.returncode != 0:
        raise SemanticRetrievalError(_command_error(embedded))


def _run(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def _command_error(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr.strip() or completed.stdout.strip() or "QMD command failed")[-1000:]


def _normalized_signature(
    normalized_dir: Path,
) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for path in sorted(normalized_dir.glob("**/*.md")):
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append(
            (
                str(path.resolve()),
                stat.st_size,
                stat.st_mtime_ns,
            )
        )
    return tuple(signature)


def _resolve_result_path(
    value: str,
    normalized_dir: Path,
    allowed: dict[str, Path],
) -> Path | None:
    raw = value.strip()
    if raw.startswith("qmd://"):
        raw = raw.split("/", 3)[-1]
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.resolve()
    direct = (normalized_dir / candidate).resolve()
    if str(direct) in allowed:
        return direct
    by_name = [path for path in allowed.values() if path.name == candidate.name]
    return by_name[0] if len(by_name) == 1 else None
