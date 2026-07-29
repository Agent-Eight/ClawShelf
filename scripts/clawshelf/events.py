from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import ShelfConfig, load_or_create_config
from .creativity_score import (
    CreativityCandidate,
    CreativityRunner,
    CreativityScoreCandidate,
    CreativityScoreError,
    CreativityScoreRequest,
    CreativityScoreResult,
    MatchedEvidence,
    ScoreBreakdown,
    deterministic_score,
    evidence_packet,
    ground_host_result,
    is_p1,
    merge_semantic_candidates,
    retrieve_candidates,
)
from .idea import IdeaCandidate
from .normalize import NormalizedRecord, parse_normalized_record
from .semantic_retrieval import (
    SemanticRetrievalResult,
    SemanticRetriever,
)


EVENT_SCHEMA = "clawshelf.watch-event"
CREATIVITY_THRESHOLD = 13
MIN_CONFIDENCE = 0.65
CANDIDATE_LIMIT = 10


@dataclass
class LinkedSource:
    new_source_path: str
    linked_source_path: str
    normalized_record_path: str
    retrieval_path: list[str]
    bridge_concepts: list[str]
    matched_terms: list[str]
    creativity_score: int
    score_breakdown: dict[str, int]
    confidence: float
    verdict: str
    scoring_method: str
    matched_evidence: list[dict[str, str]] = field(default_factory=list)
    idea_candidates: list[dict] = field(default_factory=list)
    model: str = ""
    idea_type: str = ""
    idea_relation: str = ""
    semantic_similarity: float | None = None


@dataclass
class NormalizationOutcome:
    source: str
    status: str
    record_path: str = ""
    coverage: str = "none"
    warnings: list[str] = field(default_factory=list)
    key_arguments: list[str] = field(default_factory=list)


@dataclass
class WatchEvent:
    schema: str
    created_at: str
    folder: str
    trigger: str
    status: str
    classification: str | None
    priority: str | None
    classification_reason: str
    reason: str
    new_files: list[str]
    linked_sources: list[LinkedSource] = field(default_factory=list)
    creativity_score: int | None = None
    score_breakdown: dict[str, int] | None = None
    confidence: float | None = None
    verdict: str = "not_scored"
    candidate_retrieval_path: list[str] = field(default_factory=list)
    matched_evidence: list[dict[str, str]] = field(default_factory=list)
    scoring_method: str = "not_scored"
    model: str = ""
    scoring_error: str = ""
    idea_spark: str = ""
    recommended_next_action: str = ""
    push_target: str = "host_decides"
    normalization_warnings: list[str] = field(default_factory=list)
    normalization_outcomes: list[NormalizationOutcome] = field(default_factory=list)
    config_fingerprint: str = ""
    notification_policy: str = "p1_p2"
    semantic_retrieval: dict = field(default_factory=dict)
    synthesis_brief_update: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CreativityScoringOptions:
    mode: str = "off"
    model: str = ""
    creativity_threshold: int = CREATIVITY_THRESHOLD
    min_confidence: float = MIN_CONFIDENCE
    candidate_limit: int = CANDIDATE_LIMIT
    novelty_preference: float = 0.5
    semantic_retrieval: str = "off"
    semantic_candidate_target: int = 3
    shelf_plan: dict[str, str] = field(default_factory=dict)
    runner: CreativityRunner | None = None
    semantic_retriever: SemanticRetriever | None = None


ScoredCandidate = tuple[Path, CreativityCandidate, CreativityScoreResult]


def classify_new_files(
    folder: Path,
    new_files: list[Path],
    push_target: str = "host_decides",
    creativity_options: CreativityScoringOptions | None = None,
    normalization_warnings: list[str] | None = None,
    normalization_outcomes: list[NormalizationOutcome] | None = None,
    config: ShelfConfig | None = None,
) -> WatchEvent:
    root = folder.resolve()
    config = config or load_or_create_config(root)
    options = creativity_options or CreativityScoringOptions()
    outcomes = normalization_outcomes or []
    new_record_paths = _matching_normalized_records(root, new_files)
    if _normalization_deferred(new_files, outcomes) or len(new_record_paths) < len(new_files):
        reason = _missing_normalized_reason(new_files, outcomes)
        return _event(
            root,
            new_files,
            config,
            push_target,
            status="intake_deferred",
            classification=None,
            classification_reason=reason,
            reason=reason,
            recommended_next_action="先完成 normalization 和 validation，再进行创意评分。",
            normalization_warnings=normalization_warnings,
            normalization_outcomes=outcomes,
        )

    parsed_records = _parsed_records(root)
    existing_records = [
        (path, record)
        for path, record in parsed_records
        if path.resolve() not in new_record_paths
    ]
    prior_new_records: list[tuple[Path, NormalizedRecord]] = []
    scored: list[ScoredCandidate] = []
    scoring_errors: list[str] = []
    semantic_errors: list[str] = []
    semantic_audits: list[dict] = []
    for new_file in new_files:
        new_path = _new_source_record(root, new_file, new_record_paths)
        if new_path is None:
            continue
        new_record = _parse_record(new_path)
        if new_record is None:
            continue
        records = [*existing_records, *prior_new_records]
        candidates = retrieve_candidates(
            new_record,
            records,
            candidate_limit=options.candidate_limit,
            novelty_preference=options.novelty_preference,
        )
        deterministic_count = len(candidates)
        semantic_result = _semantic_retrieval(
            new_path,
            new_record,
            records,
            candidates,
            options,
        )
        if semantic_result.status == "unavailable" and semantic_result.error:
            semantic_errors.append(semantic_result.error)
        candidates = merge_semantic_candidates(
            candidates,
            semantic_result,
            records,
            candidate_limit=options.candidate_limit,
            novelty_preference=options.novelty_preference,
        )
        semantic_audits.append(
            {
                "new_record_path": str(new_path),
                "backend": semantic_result.backend,
                "mode": options.semantic_retrieval,
                "status": semantic_result.status,
                "deterministic_candidate_count": deterministic_count,
                "semantic_candidate_count": len(semantic_result.hits),
                "candidate_target": min(
                    options.semantic_candidate_target,
                    options.candidate_limit,
                ),
                "hits": [
                    {
                        "path": hit.path,
                        "similarity": hit.similarity,
                    }
                    for hit in semantic_result.hits
                ],
                "error": semantic_result.error,
            }
        )
        prior_new_records.append((new_path, new_record))
        deterministic = [(candidate, deterministic_score(candidate)) for candidate in candidates]
        if options.mode in {"auto", "required"} and candidates:
            try:
                source_scores = _host_score(
                    new_path,
                    new_record,
                    candidates,
                    deterministic,
                    options,
                )
            except CreativityScoreError as exc:
                scoring_errors.append(str(exc))
                if options.mode == "required":
                    continue
                source_scores = deterministic
        else:
            source_scores = deterministic
        scored.extend(
            (new_file.resolve(), candidate, result)
            for candidate, result in source_scores
        )

    scored = _dedupe_scored(scored)
    if options.semantic_retrieval == "required" and semantic_errors:
        reason = f"语义候选召回不可用，intake 已延后：{semantic_errors[0]}"
        return _event(
            root,
            new_files,
            config,
            push_target,
            status="intake_deferred",
            classification=None,
            classification_reason=reason,
            reason=reason,
            recommended_next_action="修复 QMD vector retrieval 后重新处理。",
            scoring_error=semantic_errors[0],
            semantic_retrieval=_semantic_audit_summary(
                options,
                semantic_audits,
            ),
            normalization_warnings=normalization_warnings,
            normalization_outcomes=outcomes,
        )
    if options.mode == "required" and scoring_errors and not scored:
        reason = f"创意评分不可用，intake 已延后：{scoring_errors[0]}"
        return _event(
            root,
            new_files,
            config,
            push_target,
            status="intake_deferred",
            classification=None,
            classification_reason=reason,
            reason=reason,
            recommended_next_action="修复 host creativity scorer 后重新处理。",
            scoring_error=scoring_errors[0],
            semantic_retrieval=_semantic_audit_summary(options, semantic_audits),
            normalization_warnings=normalization_warnings,
            normalization_outcomes=outcomes,
        )

    ranked = sorted(
        scored,
        key=lambda item: (item[2].creativity_score, item[2].confidence),
        reverse=True,
    )[:5]
    links = [
        _linked_source(root, new_source, candidate, result)
        for new_source, candidate, result in ranked
    ]
    strongest = ranked[0][2] if ranked else None
    classification = (
        "P1"
        if strongest
        and is_p1(
            strongest,
            threshold=options.creativity_threshold,
            min_confidence=options.min_confidence,
        )
        else "P2"
    )
    if classification == "P1":
        reason = "创意连接分、置信度、verdict 与双向证据均达到 P1 门槛。"
        next_action = ""
        spark = _idea_spark(root, ranked)
    elif strongest:
        reason = _p2_reason(strongest, options)
        next_action = "来源已入库；保留评分结果供后续检索。"
        spark = ""
    else:
        reason = "未召回可评分的跨记录候选；来源已完成入库。"
        next_action = "来源已入库；无需主动研究动作。"
        spark = ""
    retrieval_paths = sorted(
        {
            path
            for _, candidate, _ in ranked
            for path in candidate.retrieval_path
        }
    )
    matched_evidence = (
        [asdict(item) for item in strongest.matched_evidence]
        if strongest
        else []
    )
    return _event(
        root,
        new_files,
        config,
        push_target,
        status="classified",
        classification=classification,
        classification_reason=reason,
        reason=reason,
        linked_sources=links,
        creativity_score=strongest.creativity_score if strongest else None,
        score_breakdown=asdict(strongest.breakdown) if strongest else None,
        confidence=strongest.confidence if strongest else None,
        verdict=strongest.verdict if strongest else "not_scored",
        candidate_retrieval_path=retrieval_paths,
        matched_evidence=matched_evidence,
        scoring_method=strongest.method if strongest else "not_scored",
        model=strongest.model if strongest else options.model,
        scoring_error=scoring_errors[0] if scoring_errors else "",
        semantic_retrieval=_semantic_audit_summary(options, semantic_audits),
        idea_spark=spark,
        recommended_next_action=next_action,
        normalization_warnings=normalization_warnings,
        normalization_outcomes=outcomes,
    )


def write_event(folder: Path, event: WatchEvent) -> Path:
    events_dir = folder.resolve() / "clawshelf" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    suffix = (event.classification or event.status).lower()
    path = events_dir / f"{stamp}-{suffix}.json"
    path.write_text(
        json.dumps(event.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _event(
    root: Path,
    new_files: list[Path],
    config: ShelfConfig,
    push_target: str,
    *,
    status: str,
    classification: str | None,
    classification_reason: str,
    reason: str,
    linked_sources: list[LinkedSource] | None = None,
    creativity_score: int | None = None,
    score_breakdown: dict[str, int] | None = None,
    confidence: float | None = None,
    verdict: str = "not_scored",
    candidate_retrieval_path: list[str] | None = None,
    matched_evidence: list[dict[str, str]] | None = None,
    scoring_method: str = "not_scored",
    model: str = "",
    scoring_error: str = "",
    idea_spark: str = "",
    recommended_next_action: str = "",
    normalization_warnings: list[str] | None = None,
    normalization_outcomes: list[NormalizationOutcome] | None = None,
    semantic_retrieval: dict | None = None,
) -> WatchEvent:
    return WatchEvent(
        schema=EVENT_SCHEMA,
        created_at=datetime.now(timezone.utc).isoformat(),
        folder=str(root),
        trigger="file_created_or_changed",
        status=status,
        classification=classification,
        priority=classification,
        classification_reason=classification_reason,
        reason=reason,
        new_files=[str(path.resolve()) for path in new_files],
        linked_sources=linked_sources or [],
        creativity_score=creativity_score,
        score_breakdown=score_breakdown,
        confidence=confidence,
        verdict=verdict,
        candidate_retrieval_path=candidate_retrieval_path or [],
        matched_evidence=matched_evidence or [],
        scoring_method=scoring_method,
        model=model,
        scoring_error=scoring_error,
        idea_spark=idea_spark,
        recommended_next_action=recommended_next_action,
        push_target=push_target,
        normalization_warnings=(normalization_warnings or [])[:10],
        normalization_outcomes=normalization_outcomes or [],
        config_fingerprint=config.fingerprint,
        notification_policy=config.notification_policy,
        semantic_retrieval=semantic_retrieval or {},
    )


def _host_score(
    new_path: Path,
    new_record: NormalizedRecord,
    candidates: list[CreativityCandidate],
    deterministic: list[tuple[CreativityCandidate, CreativityScoreResult]],
    options: CreativityScoringOptions,
) -> list[tuple[CreativityCandidate, CreativityScoreResult]]:
    if options.runner is None:
        raise CreativityScoreError("creativity scorer is not configured")
    request = CreativityScoreRequest(
        new_record_path=str(new_path),
        new_record=evidence_packet(new_record),
        candidates=[
            CreativityScoreCandidate(
                linked_record_path=candidate.linked_record_path,
                linked_record=evidence_packet(candidate.linked_record),
                retrieval_path=candidate.retrieval_path,
                bridge_concepts=candidate.bridge_concepts,
                semantic_similarity=candidate.semantic_similarity,
            )
            for candidate in candidates
        ],
        shelf_plan=options.shelf_plan,
        novelty_preference=options.novelty_preference,
    )
    results = options.runner(request, options.model)
    fallbacks = {candidate.linked_record_path: result for candidate, result in deterministic}
    return [
        (
            candidate,
            ground_host_result(
                results[candidate.linked_record_path],
                new_record,
                candidate.linked_record,
            )
            if candidate.linked_record_path in results
            else fallbacks[candidate.linked_record_path],
        )
        for candidate in candidates
    ]


def _linked_source(
    root: Path,
    new_source: Path,
    candidate: CreativityCandidate,
    result: CreativityScoreResult,
) -> LinkedSource:
    top_idea = candidate.idea_candidates[0] if candidate.idea_candidates else None
    return LinkedSource(
        new_source_path=str(new_source.resolve()),
        linked_source_path=_original_source_path(
            root,
            candidate.linked_record.frontmatter.get("source", ""),
        ),
        normalized_record_path=candidate.linked_record_path,
        retrieval_path=candidate.retrieval_path,
        bridge_concepts=candidate.bridge_concepts,
        matched_terms=[match.term for match in candidate.matched_terms],
        creativity_score=result.creativity_score,
        score_breakdown=asdict(result.breakdown),
        confidence=result.confidence,
        verdict=result.verdict,
        scoring_method=result.method,
        matched_evidence=[asdict(item) for item in result.matched_evidence],
        idea_candidates=[
            {
                **asdict(item),
                "total_score": item.total_score,
            }
            for item in candidate.idea_candidates[:5]
        ],
        model=result.model,
        idea_type=top_idea.idea_type if top_idea else "",
        idea_relation=_idea_relation(top_idea),
        semantic_similarity=candidate.semantic_similarity,
    )


def _semantic_retrieval(
    new_path: Path,
    new_record: NormalizedRecord,
    records: list[tuple[Path, NormalizedRecord]],
    candidates: list[CreativityCandidate],
    options: CreativityScoringOptions,
) -> SemanticRetrievalResult:
    if options.semantic_retrieval == "off":
        return SemanticRetrievalResult(status="off")
    target = min(options.semantic_candidate_target, options.candidate_limit)
    missing = target - len(candidates)
    if missing <= 0:
        return SemanticRetrievalResult(status="not_needed")
    if options.semantic_retriever is None:
        return SemanticRetrievalResult(
            status="unavailable",
            error="QMD vector retriever is not configured",
        )
    return options.semantic_retriever(
        new_path,
        new_record,
        records,
        missing,
    )


def _semantic_audit_summary(
    options: CreativityScoringOptions,
    audits: list[dict],
) -> dict:
    statuses = [str(audit.get("status", "")) for audit in audits]
    if "unavailable" in statuses:
        status = "unavailable"
    elif "used" in statuses:
        status = "used"
    elif "not_needed" in statuses:
        status = "not_needed"
    elif "off" in statuses or options.semantic_retrieval == "off":
        status = "off"
    else:
        status = "not_used"
    return {
        "backend": "qmd_vector",
        "mode": options.semantic_retrieval,
        "status": status,
        "candidate_target": min(
            options.semantic_candidate_target,
            options.candidate_limit,
        ),
        "queries": audits,
    }


def _idea_relation(candidate: IdeaCandidate | None) -> str:
    if candidate is None:
        return ""
    return f"{candidate.new_signal_type} → {candidate.linked_signal_type}"


def _dedupe_scored(
    scored: list[ScoredCandidate],
) -> list[ScoredCandidate]:
    best: dict[str, ScoredCandidate] = {}
    for item in scored:
        path = item[1].linked_record_path
        current = best.get(path)
        if current is None or (
            item[2].creativity_score,
            item[2].confidence,
        ) > (
            current[2].creativity_score,
            current[2].confidence,
        ):
            best[path] = item
    return list(best.values())


def _p2_reason(
    result: CreativityScoreResult,
    options: CreativityScoringOptions,
) -> str:
    failures: list[str] = []
    if result.creativity_score < options.creativity_threshold:
        failures.append(
            f"creativity_score {result.creativity_score} < {options.creativity_threshold}"
        )
    if result.confidence < options.min_confidence:
        failures.append(f"confidence {result.confidence:.2f} < {options.min_confidence:.2f}")
    if result.verdict != "p1_candidate":
        failures.append(f"verdict={result.verdict}")
    if not any(item.new_evidence and item.linked_evidence for item in result.matched_evidence):
        failures.append("缺少双向来源证据")
    return "未达到 P1 门槛：" + "；".join(failures) + "。来源已完成入库。"


def _idea_spark(
    root: Path,
    ranked: list[ScoredCandidate],
) -> str:
    if not ranked:
        return ""
    new_source, candidate, _ = ranked[0]
    names = new_source.name
    linked = _source_label(
        _original_source_path(
            root,
            candidate.linked_record.frontmatter.get("source", ""),
        )
    )
    if candidate.idea_candidates:
        idea = candidate.idea_candidates[0]
        label = "创新" if idea.idea_type == "innovation" else "巩固"
        return (
            f"{names} 与 {linked} 存在{label}型连接："
            f"{idea.new_signal_type} 可连接 {idea.linked_signal_type}。"
        )
    concepts = "、".join(candidate.bridge_concepts[:3])
    return f"{names} 与 {linked} 通过结构化概念桥接：{concepts}。"


def _original_source_path(root: Path, source: str) -> str:
    value = _clean_source_value(source)
    if not value:
        return ""
    if "://" in value:
        return value
    path = Path(value)
    return str(path if path.is_absolute() else (root / path).resolve())


def _source_label(source: str) -> str:
    return source if "://" in source else Path(source).name


def _normalization_deferred(
    sources: list[Path],
    outcomes: list[NormalizationOutcome],
) -> bool:
    source_keys = {str(source.resolve()) for source in sources}
    return any(
        outcome.source in source_keys
        and outcome.status in {
            "invalid",
            "validation_failed",
            "failed",
            "llm_unavailable",
            "unsupported",
        }
        for outcome in outcomes
    )


def _missing_normalized_reason(
    sources: list[Path],
    outcomes: list[NormalizationOutcome],
) -> str:
    source_keys = {str(source.resolve()) for source in sources}
    failure = next(
        (
            outcome
            for outcome in outcomes
            if outcome.source in source_keys
            and outcome.status in {
                "invalid",
                "validation_failed",
                "failed",
                "llm_unavailable",
                "unsupported",
            }
        ),
        None,
    )
    if failure is None:
        return "检测到新来源，但没有通过 validation 的 normalized record。"
    detail = failure.warnings[0] if failure.warnings else failure.status
    return f"normalization 未完成：{Path(failure.source).name}: {detail}"


def _parsed_records(folder: Path) -> list[tuple[Path, NormalizedRecord]]:
    parsed: list[tuple[Path, NormalizedRecord]] = []
    for path in _normalized_records(folder):
        record = _parse_record(path)
        if record is not None:
            parsed.append((path, record))
    return parsed


def _normalized_records(folder: Path) -> list[Path]:
    normalized = folder / "clawshelf" / "normalized"
    if not normalized.is_dir():
        return []
    return sorted(path for path in normalized.glob("**/*.md") if path.is_file())


def _new_source_record(
    folder: Path,
    source: Path,
    new_record_paths: set[Path],
) -> Path | None:
    return next(
        (
            path
            for path in _normalized_records(folder)
            if path.resolve() in new_record_paths
            and _record_matches_source(path, source, folder)
        ),
        None,
    )


def _matching_normalized_records(folder: Path, sources: list[Path]) -> set[Path]:
    source_keys = {key for source in sources for key in _source_keys(source, folder)}
    return {
        record.resolve()
        for record in _normalized_records(folder)
        if source_keys and _record_source(record) in source_keys
    }


def _record_matches_source(record: Path, source: Path, folder: Path) -> bool:
    record_source = _record_source(record)
    return bool(record_source and record_source in _source_keys(source, folder))


def _record_source(record: Path) -> str:
    try:
        lines = record.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return ""
        if stripped.startswith("source:"):
            return _clean_source_value(stripped.split(":", 1)[1])
    return ""


def _source_keys(source: Path, folder: Path) -> set[str]:
    resolved = source.resolve()
    keys = {source.name, str(source), str(resolved)}
    try:
        keys.add(str(resolved.relative_to(folder.resolve())))
    except ValueError:
        pass
    return {_clean_source_value(key) for key in keys if key}


def _clean_source_value(value: str) -> str:
    return value.strip().strip("'\"`")


def _parse_record(record: Path) -> NormalizedRecord | None:
    try:
        return parse_normalized_record(record.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        return None
