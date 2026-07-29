from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.events import CreativityScoringOptions, classify_new_files
from clawshelf.config import load_or_create_config
from clawshelf.keyword_worker import KeywordExtractionPacket, SectionEvidence
from clawshelf.creativity_score import (
    CreativityScoreError,
    CreativityScoreResult,
    MatchedEvidence,
    ScoreBreakdown,
    parse_creativity_scores,
)
from openclaw_watch_adapter import (
    NOTIFICATION_SCHEMA,
    _handle_result,
    _creativity_options,
    build_notification,
    deliver_notification,
    keyword_worker_from_args,
    retry_pending_notifications,
    write_notification,
)
from clawshelf.watch import _poll_folder, _reconcile_startup, creativity_options_from_config, handle_files, should_ignore, stable_files

def _normalized_record(source: str, term: str, evidence: str = "p. 1", weight: int = 5) -> str:
    return f"""---
source: {source}
source_type: md
source_sha256: abc123
extraction_method: text
confidence: High
---

# {source}

## Summary

This source studies {term} as a research signal (source: `{source}`, p. 1). It uses source-backed evidence to describe methods and findings (source: `{source}`, p. 2). It notes scope limitations for downstream comparison (source: `{source}`, p. 3).

## Topics

- {term}

## Keywords

- `{term}` — central source concept; evidence: {evidence}
- `volatility prediction` — related finding; evidence: p. 2
- `retail cash flows` — related topic; evidence: p. 3
- `investor heterogeneity` — related topic; evidence: p. 4
- `detrended fluctuation analysis` — method; evidence: p. 5
- `rolling windows` — method detail; evidence: p. 6
- `net flows` — comparison variable; evidence: p. 7
- `regime sensitivity` — limitation/finding; evidence: p. 8

## RAG Terms

- term: {term}
  weight: {weight}
  aliases: none
  evidence: {evidence}
  role: topic

## Key Claims

- {term} is central to the source (source: `{source}`, {evidence}).

## Methods or Basis

Source-backed method description (source: `{source}`, p. 2).

## Evidence Notes

- Original source: `{source}`

## Limitations

- Scope is limited to the test fixture; evidence: p. 3.

## Warnings

- None.
"""


def _bridge_record(
    source: str,
    title: str,
    rag_term: str,
    signal: str,
    dendrite_signal: str = "Test prediction market execution under realistic constraints.",
) -> str:
    return f"""---
source: {source}
source_type: md
source_sha256: abc123
extraction_method: text
confidence: High
---

# {title}

## Summary

{signal} (evidence: section: Summary).

## Keywords

- `{rag_term}` — source concept; evidence: section: Summary

## RAG Terms

- term: {rag_term}
  weight: 5
  aliases: none
  evidence: section: Summary
  role: method

## Key Claims

- {signal} (evidence: section: Claims).

## Methods or Basis

{signal} (evidence: section: Methods).

## Axon Signals

- type: Strong Method
  signal: {signal}
  evidence: section: Methods

## Dendrite Signals

- type: Extension Hint
  signal: {dendrite_signal}
  evidence: section: Limitations

## Limitations

### Improvement Directions

- category: Evaluation
  direction: Test execution
  expected_value: Better evidence
  evidence_or_rationale: section: Limitations

## Idea Signals

- Connect prediction market methods (evidence: section: Methods).

## Connection Hooks

- Prediction market execution bridge (evidence: section: Methods).
"""


def _creativity_result(
    score: int,
    confidence: float = 0.8,
    verdict: str = "p1_candidate",
    new_evidence: str = "p. 1",
    linked_evidence: str = "p. 1",
) -> CreativityScoreResult:
    relationship_strength = min(score, 5)
    remaining = max(score - relationship_strength, 0)
    evidence_alignment = min(remaining, 5)
    remaining = max(remaining - evidence_alignment, 0)
    novelty_or_tension = min(remaining, 5)
    remaining = max(remaining - novelty_or_tension, 0)
    actionability = min(remaining, 5)
    return CreativityScoreResult(
        breakdown=ScoreBreakdown(
            relationship=relationship_strength,
            evidence=evidence_alignment,
            novelty_or_tension=novelty_or_tension,
            actionability=actionability,
            risk=0,
        ),
        confidence=confidence,
        matched_evidence=[
            MatchedEvidence(
                signal="execution benchmark link",
                new_evidence=new_evidence,
                linked_evidence=linked_evidence,
                why_it_matters="both evaluate trading agent behavior",
            )
        ],
        verdict=verdict,
        method="host",
        model="host-default",
    )


class WatchTests(unittest.TestCase):
    def _run_cases(self, *names: str) -> None:
        for name in names:
            with self.subTest(case=name.removeprefix("_case_")):
                getattr(self, name)()

    def test_classification_scenarios(self) -> None:
        self._run_cases(
            "_case_should_ignore_generated_and_transient_paths",
            "_case_p1_when_new_file_links_to_existing_records",
            "_case_p2_when_new_file_has_no_strong_connection",
            "_case_generic_only_overlap_does_not_trigger_p1",
            "_case_prefers_new_normalized_record_and_excludes_self_link",
            "_case_dedupes_linked_sources_across_multiple_new_files",
        )

    def test_creativity_scoring_scenarios(self) -> None:
        self._run_cases(
            "_case_creativity_scorer_can_promote_weak_candidate_to_p1",
            "_case_creativity_scorer_low_score_keeps_p2",
            "_case_creativity_scorer_batches_candidates_and_preserves_missing_fallback",
            "_case_parse_batched_creativity_scores",
            "_case_creativity_scorer_auto_falls_back_on_invalid_response",
            "_case_creativity_scorer_required_defers_on_invalid_response",
            "_case_creativity_scorer_not_called_without_candidates",
            "_case_host_evidence_must_be_grounded",
            "_case_structural_relation_retrieval_does_not_require_rag_match",
            "_case_quantpedia_prediction_market_bench_event_to_notification",
        )

    def test_configuration_scenarios(self) -> None:
        self._run_cases(
            "_case_config_configures_creativity_options",
            "_case_watch_defaults_enable_creativity_auto_host_model",
            "_case_openclaw_adapter_config_configures_creativity_options",
            "_case_openclaw_adapter_defaults_enable_creativity_auto_host_model",
            "_case_openclaw_adapter_keyword_worker_uses_runtime_target",
        )

    def test_watch_pipeline_scenarios(self) -> None:
        self._run_cases(
            "_case_handle_files_writes_event",
            "_case_stable_files_uses_one_batch_sleep",
            "_case_poll_loop_continues_after_handle_failure",
            "_case_handle_files_records_normalization_warnings",
            "_case_handle_files_updates_brief_before_p1_event",
            "_case_handle_files_records_brief_update_failure",
            "_case_p2_does_not_update_synthesis_brief",
            "_case_validation_failure_defers_without_p2",
            "_case_partial_normalization_is_a_successful_intake",
            "_case_startup_reconciliation_processes_stale_sources",
        )

    def test_notification_rendering_scenarios(self) -> None:
        self._run_cases(
            "_case_openclaw_notification_notifies_p1_and_p2_by_default",
            "_case_openclaw_notification_message_uses_markdown_template",
            "_case_openclaw_notification_maps_multiple_new_sources",
            "_case_openclaw_notification_preserves_linked_url",
            "_case_openclaw_notification_falls_back_to_compact_keywords",
            "_case_p1_notification_reports_brief_failure",
            "_case_p1_notification_caps_ideas_at_three",
            "_case_p2_notification_does_not_claim_a_research_connection",
            "_case_p2_notification_groups_multiple_sources",
            "_case_openclaw_notification_message_shows_creativity_reason",
            "_case_scratch_p1_and_p2_watch_adapter_directives",
        )

    def test_notification_delivery_scenarios(self) -> None:
        self._run_cases(
            "_case_notification_is_persisted_under_clawshelf_notifications",
            "_case_delivery_binds_session_key_and_provider_channel",
            "_case_delivery_falls_back_to_channel_without_session_key",
            "_case_delivery_missing_binary_and_timeout_return_failed",
            "_case_no_deliver_notification_is_not_retryable",
        )

    def test_notification_state_scenarios(self) -> None:
        self._run_cases(
            "_case_notification_ledger_suppresses_identical_content",
            "_case_pending_retry_is_capped_at_three_attempts",
            "_case_failed_notification_retries_after_route_change",
        )

    def _case_should_ignore_generated_and_transient_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(should_ignore(root / "clawshelf" / "events" / "x.json", root))
            self.assertTrue(should_ignore(root / ".DS_Store", root))
            self.assertTrue(should_ignore(root / "paper.pdf.download", root))
            self.assertFalse(should_ignore(root / "sources" / "paper.md", root))

    def _case_p1_when_new_file_links_to_existing_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "river.md").write_text(_normalized_record("existing.md", "river restoration"), encoding="utf-8")
            (normalized / "new-river-note.md").write_text(
                _normalized_record("new-river-note.md", "river restoration"),
                encoding="utf-8",
            )
            source = root / "new-river-note.md"
            source.write_text(
                "river restoration sediment budget monitoring evidence creates new comparison",
                encoding="utf-8",
            )
            event = classify_new_files(root, [source])
            self.assertEqual(event.priority, "P1")
            self.assertTrue(event.linked_sources)
            self.assertIn("river restoration", event.linked_sources[0].matched_terms)
            self.assertTrue(event.linked_sources[0].matched_evidence)
            self.assertIsInstance(event.linked_sources[0].idea_candidates, list)
            self.assertEqual(event.push_target, "host_decides")

    def _case_p2_when_new_file_has_no_strong_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "river.md").write_text(_normalized_record("existing.md", "river restoration"), encoding="utf-8")
            source = root / "shopping-list.md"
            source.write_text("apples bananas oranges weekend groceries", encoding="utf-8")
            event = classify_new_files(root, [source])
            self.assertIsNone(event.priority)
            self.assertEqual(event.status, "intake_deferred")
            self.assertIn("normalized record", event.reason)
            self.assertEqual(event.idea_spark, "")

    def _case_generic_only_overlap_does_not_trigger_p1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(_normalized_record("existing.md", "abstract"), encoding="utf-8")
            (normalized / "new-note.md").write_text(_normalized_record("new-note.md", "abstract"), encoding="utf-8")
            source = root / "new-note.md"
            source.write_text("abstract method result market paper", encoding="utf-8")

            event = classify_new_files(root, [source])

            self.assertEqual(event.priority, "P2")
            self.assertEqual(event.linked_sources, [])

    def _case_prefers_new_normalized_record_and_excludes_self_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            existing = normalized / "retail-flow.md"
            existing.write_text(_normalized_record("existing.md", "retail cash flows"), encoding="utf-8")
            new_record = normalized / "new-note.md"
            new_record.write_text(_normalized_record("raw-drop.txt", "retail cash flows"), encoding="utf-8")
            source = root / "raw-drop.txt"
            source.write_text("opaque upload placeholder", encoding="utf-8")

            event = classify_new_files(root, [source])

            self.assertEqual(event.priority, "P1")
            self.assertTrue(event.linked_sources)
            link = event.linked_sources[0]
            self.assertEqual(Path(link.new_source_path).name, source.name)
            self.assertEqual(Path(link.linked_source_path).name, "existing.md")
            self.assertEqual(Path(link.normalized_record_path).name, existing.name)
            self.assertNotIn(
                new_record.name,
                [Path(item.normalized_record_path).name for item in event.linked_sources],
            )

    def _case_dedupes_linked_sources_across_multiple_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            existing = normalized / "existing.md"
            existing.write_text(
                _normalized_record("existing.pdf", "retail cash flows"),
                encoding="utf-8",
            )
            for source_name, record_name in (
                ("new-a.pdf", "new-a.md"),
                ("new-b.pdf", "new-b.md"),
            ):
                (root / source_name).write_text(
                    "retail cash flows investor evidence",
                    encoding="utf-8",
                )
                (normalized / record_name).write_text(
                    _normalized_record(source_name, "retail cash flows"),
                    encoding="utf-8",
                )

            def runner(request, model):
                score = 13 if request.new_record_path.endswith("new-a.md") else 18
                return {
                    candidate.linked_record_path: _creativity_result(score)
                    for candidate in request.candidates
                }

            event = classify_new_files(
                root,
                [root / "new-a.pdf", root / "new-b.pdf"],
                creativity_options=CreativityScoringOptions(
                    mode="auto",
                    runner=runner,
                ),
            )

            self.assertEqual(event.priority, "P1")
            existing_links = [
                link
                for link in event.linked_sources
                if Path(link.normalized_record_path).name == existing.name
            ]
            self.assertEqual(len(existing_links), 1)
            self.assertEqual(
                Path(existing_links[0].new_source_path).name,
                "new-b.pdf",
            )
            self.assertEqual(
                Path(existing_links[0].linked_source_path).name,
                "existing.pdf",
            )

    def _case_creativity_scorer_can_promote_weak_candidate_to_p1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(
                _normalized_record("existing.md", "trading agent benchmark", weight=1),
                encoding="utf-8",
            )
            (normalized / "new-note.md").write_text(
                _normalized_record("new-note.md", "trading agent benchmark", weight=1),
                encoding="utf-8",
            )
            source = root / "new-note.md"
            source.write_text("prediction markets benchmark trading agents", encoding="utf-8")
            calls = []

            def runner(request, model):
                calls.append((request, model))
                return {request.candidates[0].linked_record_path: _creativity_result(14)}

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(mode="auto", runner=runner),
            )

            self.assertEqual(event.priority, "P1")
            self.assertEqual(event.scoring_method, "host")
            self.assertEqual(event.creativity_score, 14)
            self.assertEqual(event.confidence, 0.8)
            self.assertEqual(event.model, "host-default")
            self.assertEqual(calls[0][1], "")
            self.assertEqual(event.linked_sources[0].matched_evidence[0]["signal"], "execution benchmark link")

    def _case_creativity_scorer_low_score_keeps_p2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(
                _normalized_record("existing.md", "trading agent benchmark", weight=1),
                encoding="utf-8",
            )
            (normalized / "new-note.md").write_text(
                _normalized_record("new-note.md", "trading agent benchmark", weight=1),
                encoding="utf-8",
            )
            source = root / "new-note.md"
            source.write_text("prediction markets benchmark trading agents", encoding="utf-8")

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(
                    mode="auto",
                    runner=lambda request, model: {
                        request.candidates[0].linked_record_path: _creativity_result(8)
                    },
                ),
            )

            self.assertEqual(event.priority, "P2")
            self.assertEqual(event.scoring_method, "host")
            self.assertEqual(event.creativity_score, 8)

    def _case_creativity_scorer_batches_candidates_and_preserves_missing_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            for name in ("existing-a.md", "existing-b.md"):
                (normalized / name).write_text(
                    _normalized_record(name, "trading agent benchmark", weight=1),
                    encoding="utf-8",
                )
            (normalized / "new-note.md").write_text(
                _normalized_record("new-note.md", "trading agent benchmark", weight=1),
                encoding="utf-8",
            )
            source = root / "new-note.md"
            source.write_text("prediction markets benchmark trading agents", encoding="utf-8")
            calls = []

            def runner(request, model):
                calls.append(request)
                return {request.candidates[0].linked_record_path: _creativity_result(14)}

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(mode="auto", runner=runner),
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(len(calls[0].candidates), 2)
            self.assertEqual(len(event.linked_sources), 2)
            self.assertEqual(
                {link.scoring_method for link in event.linked_sources},
                {"host", "deterministic"},
            )

    def _case_parse_batched_creativity_scores(self) -> None:
        payload = {
            "scores": [
                {
                    "linked_record_path": "one.md",
                    "relationship": 4,
                    "evidence": 3,
                    "novelty_or_tension": 2,
                    "actionability": 4,
                    "risk": 1,
                    "confidence": 0.8,
                    "matched_evidence": [],
                    "verdict": "p2_intake",
                }
            ]
        }
        scores = parse_creativity_scores(json.dumps(payload))
        self.assertEqual(scores["one.md"].creativity_score, 12)

    def _case_creativity_scorer_auto_falls_back_on_invalid_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(
                _normalized_record("existing.md", "trading agent benchmark", weight=1),
                encoding="utf-8",
            )
            (normalized / "new-note.md").write_text(
                _normalized_record("new-note.md", "trading agent benchmark", weight=1),
                encoding="utf-8",
            )
            source = root / "new-note.md"
            source.write_text("prediction markets benchmark trading agents", encoding="utf-8")

            def runner(request, model):
                raise CreativityScoreError("invalid JSON")

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(mode="auto", runner=runner),
            )

            self.assertEqual(event.priority, "P1")
            self.assertEqual(event.scoring_method, "deterministic")
            self.assertIn("invalid JSON", event.scoring_error)

    def _case_creativity_scorer_required_defers_on_invalid_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(_normalized_record("existing.md", "retail cash flows"), encoding="utf-8")
            (normalized / "new-note.md").write_text(_normalized_record("new-note.md", "retail cash flows"), encoding="utf-8")
            source = root / "new-note.md"
            source.write_text("retail cash flows", encoding="utf-8")

            def runner(request, model):
                raise CreativityScoreError("host scorer unavailable")

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(mode="required", runner=runner),
            )

            self.assertIsNone(event.priority)
            self.assertEqual(event.status, "intake_deferred")
            self.assertEqual(event.scoring_method, "not_scored")
            self.assertIn("host scorer unavailable", event.reason)
            self.assertEqual(event.linked_sources, [])

    def _case_creativity_scorer_not_called_without_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(_normalized_record("existing.md", "river restoration"), encoding="utf-8")
            (normalized / "new-note.md").write_text(_normalized_record("new-note.md", "trading agent benchmark"), encoding="utf-8")
            source = root / "new-note.md"
            source.write_text("prediction markets benchmark trading agents", encoding="utf-8")

            def runner(request, model):
                raise AssertionError("creativity scorer should not be called")

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(mode="auto", runner=runner),
            )

            self.assertEqual(event.priority, "P2")
            self.assertEqual(event.linked_sources, [])

    def _case_host_evidence_must_be_grounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(
                _normalized_record("existing.md", "trading agent benchmark"),
                encoding="utf-8",
            )
            (normalized / "new-note.md").write_text(
                _normalized_record("new-note.md", "trading agent benchmark"),
                encoding="utf-8",
            )
            source = root / "new-note.md"
            source.write_text("prediction markets benchmark trading agents", encoding="utf-8")

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(
                    mode="auto",
                    runner=lambda request, model: {
                        request.candidates[0].linked_record_path: _creativity_result(
                            14,
                            new_evidence="invented new-record evidence",
                            linked_evidence="invented linked-record evidence",
                        )
                    },
                ),
            )

            self.assertEqual(event.priority, "P2")
            self.assertEqual(event.verdict, "p2_intake")
            self.assertEqual(event.matched_evidence, [])
            self.assertIn("双向来源证据", event.classification_reason)

    def _case_structural_relation_retrieval_does_not_require_rag_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "benchmark.md").write_text(
                _bridge_record(
                    "benchmark.md",
                    "Execution Evaluation",
                    "settlement fee evaluation",
                    "Benchmark execution friction across fee regimes.",
                    "Evaluate arbitrage execution across settlement fees.",
                ),
                encoding="utf-8",
            )
            (normalized / "arbitrage.md").write_text(
                _bridge_record(
                    "arbitrage.md",
                    "Strategy Screening",
                    "fragmented venue liquidity",
                    "Arbitrage screening under fragmented liquidity constraints.",
                    "Measure capital capacity under venue fragmentation.",
                ),
                encoding="utf-8",
            )
            source = root / "arbitrage.md"
            source.write_text("source", encoding="utf-8")

            event = classify_new_files(root, [source])

            self.assertEqual(event.priority, "P1")
            self.assertEqual(
                event.candidate_retrieval_path,
                ["structured_relation_candidate"],
            )
            self.assertTrue(event.matched_evidence)

    def _case_quantpedia_prediction_market_bench_event_to_notification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "benchmark.md").write_text(
                _bridge_record(
                    "benchmark.md",
                    "PredictionMarketBench",
                    "deterministic replay",
                    "Prediction market execution replay with fees and settlement.",
                ),
                encoding="utf-8",
            )
            (normalized / "quantpedia.md").write_text(
                _bridge_record(
                    "quantpedia.md",
                    "QuantPedia Strategy",
                    "inter-exchange arbitrage",
                    "Prediction market arbitrage under liquidity constraints.",
                ),
                encoding="utf-8",
            )
            benchmark_source = root / "benchmark.md"
            benchmark_source.write_text("benchmark source", encoding="utf-8")
            quantpedia_source = root / "quantpedia.md"
            quantpedia_source.write_text("quantpedia source", encoding="utf-8")

            event = classify_new_files(
                root,
                [benchmark_source, quantpedia_source],
            )
            event_path = root / "clawshelf" / "events" / "event.json"
            notification = build_notification(event_path, event.to_dict())

            self.assertEqual(event.priority, "P1")
            self.assertIsNotNone(event.creativity_score)
            self.assertIn("structured_concept_bridge", event.candidate_retrieval_path)
            self.assertIn("structured_relation_candidate", event.candidate_retrieval_path)
            self.assertTrue(event.matched_evidence)
            self.assertEqual(notification["priority"], "P1")
            self.assertIn("发现潜在研究连接", notification["message"])
            self.assertIn("quantpedia.md", notification["message"])
            self.assertIn("benchmark.md", notification["message"])

    def _case_config_configures_creativity_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_or_create_config(root)
            payload = config.to_dict()
            payload["creativity_scoring"].update({"mode": "auto", "model": "fast-model", "candidate_limit": 4})
            payload["creativity_scoring"]["advanced"] = {"threshold": 11, "min_confidence": 0.7}
            (root / "clawshelf" / "clawshelf-config.json").write_text(json.dumps(payload), encoding="utf-8")
            args = Namespace(
                creativity_scorer=None,
                creativity_model=None,
                creativity_threshold=None,
                creativity_min_confidence=None,
                novelty_preference=None,
                candidate_limit=None,
            )

            options = creativity_options_from_config(root, args)

            self.assertEqual(options.mode, "auto")
            self.assertEqual(options.model, "fast-model")
            self.assertEqual(options.creativity_threshold, 11)
            self.assertEqual(options.min_confidence, 0.7)
            self.assertEqual(options.candidate_limit, 4)

    def _case_watch_defaults_enable_creativity_auto_host_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                creativity_scorer=None,
                creativity_model=None,
                creativity_threshold=None,
                creativity_min_confidence=None,
                novelty_preference=None,
                candidate_limit=None,
            )

            with patch.dict(
                "os.environ",
                {
                    "CLAWSHELF_CREATIVITY_SCORER": "",
                    "CLAWSHELF_CREATIVITY_MODEL": "",
                    "CLAWSHELF_CREATIVITY_THRESHOLD": "",
                    "CLAWSHELF_CREATIVITY_MIN_CONFIDENCE": "",
                    "CLAWSHELF_CANDIDATE_LIMIT": "",
                },
            ):
                options = creativity_options_from_config(root, args)

            self.assertEqual(options.mode, "auto")
            self.assertEqual(options.model, "")

    def _case_openclaw_adapter_config_configures_creativity_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_or_create_config(root)
            payload = config.to_dict()
            payload["creativity_scoring"].update({"mode": "required", "model": "fast-model"})
            (root / "clawshelf" / "clawshelf-config.json").write_text(json.dumps(payload), encoding="utf-8")
            args = Namespace(
                creativity_scorer=None,
                creativity_model=None,
                creativity_threshold=None,
                creativity_min_confidence=None,
                novelty_preference=None,
                candidate_limit=None,
                openclaw_bin="openclaw",
                session_key="agent:test",
                agent_id="agent-7",
                channel="last",
            )

            with patch.dict(
                "os.environ",
                {
                    "CLAWSHELF_CREATIVITY_SCORER": "",
                    "CLAWSHELF_CREATIVITY_MODEL": "",
                    "CLAWSHELF_CREATIVITY_THRESHOLD": "",
                    "CLAWSHELF_CREATIVITY_MIN_CONFIDENCE": "",
                    "CLAWSHELF_CANDIDATE_LIMIT": "",
                },
            ):
                options = _creativity_options(root, args)

            self.assertEqual(options.mode, "required")
            self.assertEqual(options.model, "fast-model")
            self.assertIsNotNone(options.runner)

    def _case_openclaw_adapter_defaults_enable_creativity_auto_host_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                creativity_scorer=None,
                creativity_model=None,
                creativity_threshold=None,
                creativity_min_confidence=None,
                novelty_preference=None,
                candidate_limit=None,
                openclaw_bin="openclaw",
                session_key="agent:test",
                agent_id="agent-7",
                channel="last",
            )

            options = _creativity_options(root, args)

            self.assertEqual(options.mode, "auto")
            self.assertEqual(options.model, "")
            self.assertIsNotNone(options.runner)

    def _case_openclaw_adapter_keyword_worker_uses_runtime_target(self) -> None:
        args = Namespace(
            openclaw_bin="openclaw-test",
            session_key="agent:test:session",
            agent_id="agent-test",
            channel="last",
        )
        packet = KeywordExtractionPacket(
            source="paper.pdf",
            title="Paper",
            content_warning="",
            section_packets=[
                SectionEvidence(
                    heading="Abstract",
                    heading_path="Abstract",
                    role="abstract",
                    text="source text",
                )
            ],
        )
        calls = []

        with patch("openclaw_watch_adapter.run_openclaw_keyword_worker") as run:
            run.return_value = "ok"
            worker = keyword_worker_from_args(args)
            result = worker(packet, "")
            calls.append(run.call_args)

        self.assertEqual(result, "ok")
        _, kwargs = calls[0]
        self.assertEqual(kwargs["openclaw_bin"], "openclaw-test")
        self.assertEqual(kwargs["session_key"], "agent:test:session")
        self.assertEqual(kwargs["agent_id"], "agent-test")
        self.assertEqual(kwargs["channel"], "last")

    def _case_handle_files_writes_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "note.md"
            source.write_text("standalone note", encoding="utf-8")
            with patch("clawshelf.watch.stable_files", return_value=[source.resolve()]), patch("clawshelf.watch.normalize_sources", return_value=[]):
                result = handle_files(root, [source])
            self.assertIsNotNone(result)
            event_path, event = result
            self.assertTrue(event_path.exists())
            payload = json.loads(event_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["priority"], event["priority"])

    def _case_stable_files_uses_one_batch_sleep(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"{index}.txt" for index in range(5)]
            for path in paths:
                path.write_text("stable", encoding="utf-8")
            with patch("clawshelf.watch.time.sleep") as sleep:
                stable = stable_files(paths)
            self.assertEqual(set(stable), {path.resolve() for path in paths})
            sleep.assert_called_once()

    def _case_poll_loop_continues_after_handle_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("clawshelf.watch.time.sleep", side_effect=[None, None, KeyboardInterrupt]), patch(
                "clawshelf.watch._current_snapshots",
                side_effect=[{}, {}, {}],
            ), patch(
                "clawshelf.watch.handle_files",
                side_effect=[RuntimeError("bad input"), None],
            ) as handle, patch("builtins.print"):
                with self.assertRaises(KeyboardInterrupt):
                    _poll_folder(root, None, 0, "host_decides", lambda result: None)
            self.assertEqual(handle.call_count, 2)
            self.assertTrue((root / "clawshelf" / "watch.log").exists())

    def _case_handle_files_records_normalization_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "note.md"
            source.write_text("standalone note", encoding="utf-8")

            result_item = Namespace(source=source, status="llm_unavailable", warnings=["model override unavailable"])
            with patch("clawshelf.watch.stable_files", return_value=[source.resolve()]), patch(
                "clawshelf.watch.normalize_sources",
                return_value=[result_item],
            ):
                result = handle_files(root, [source])

            self.assertIsNotNone(result)
            event_path, event = result
            payload = json.loads(event_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["normalization_warnings"], ["note.md: model override unavailable"])
            self.assertIn("normalization 未完成", event["reason"])
            self.assertEqual(payload["normalization_outcomes"][0]["status"], "llm_unavailable")
            self.assertEqual(payload["normalization_outcomes"][0]["coverage"], "none")
            self.assertEqual(payload["new_files"], [str(source.resolve())])

    def _case_handle_files_updates_brief_before_p1_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(
                _normalized_record("existing.pdf", "retail cash flows"),
                encoding="utf-8",
            )
            (normalized / "new.md").write_text(
                _normalized_record("new.pdf", "retail cash flows"),
                encoding="utf-8",
            )
            source = root / "new.pdf"
            source.write_text("retail cash flows", encoding="utf-8")

            with patch(
                "clawshelf.watch.stable_files",
                return_value=[source.resolve()],
            ), patch(
                "clawshelf.watch.normalize_sources",
                return_value=[],
            ):
                event_path, event = handle_files(root, [source])

            brief = root / "clawshelf" / "clawshelf-brief.md"
            payload = json.loads(event_path.read_text(encoding="utf-8"))
            self.assertEqual(event["priority"], "P1")
            self.assertEqual(
                event["synthesis_brief_update"]["status"],
                "updated",
            )
            self.assertEqual(
                payload["synthesis_brief_update"],
                event["synthesis_brief_update"],
            )
            self.assertTrue(brief.is_file())
            brief_text = brief.read_text(encoding="utf-8")
            self.assertIn("new.pdf", brief_text)
            self.assertIn("existing.pdf", brief_text)
            self.assertNotIn("clawshelf/normalized/existing.md", brief_text)

    def _case_handle_files_records_brief_update_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing.md").write_text(
                _normalized_record("existing.pdf", "retail cash flows"),
                encoding="utf-8",
            )
            (normalized / "new.md").write_text(
                _normalized_record("new.pdf", "retail cash flows"),
                encoding="utf-8",
            )
            source = root / "new.pdf"
            source.write_text("retail cash flows", encoding="utf-8")

            with patch(
                "clawshelf.watch.stable_files",
                return_value=[source.resolve()],
            ), patch(
                "clawshelf.watch.normalize_sources",
                return_value=[],
            ), patch(
                "clawshelf.watch.update_synthesis_brief",
                side_effect=OSError("brief is read-only"),
            ):
                event_path, event = handle_files(root, [source])

            self.assertEqual(event["priority"], "P1")
            self.assertEqual(
                event["synthesis_brief_update"]["status"],
                "failed",
            )
            self.assertIn(
                "brief is read-only",
                event["synthesis_brief_update"]["error"],
            )
            self.assertTrue(event_path.is_file())

    def _case_p2_does_not_update_synthesis_brief(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "new.md").write_text(
                _normalized_record("new.pdf", "standalone unique topic"),
                encoding="utf-8",
            )
            source = root / "new.pdf"
            source.write_text("standalone unique topic", encoding="utf-8")

            with patch(
                "clawshelf.watch.stable_files",
                return_value=[source.resolve()],
            ), patch(
                "clawshelf.watch.normalize_sources",
                return_value=[],
            ), patch(
                "clawshelf.watch.update_synthesis_brief",
            ) as update:
                _event_path, event = handle_files(root, [source])

            self.assertEqual(event["priority"], "P2")
            self.assertEqual(event["synthesis_brief_update"], {})
            update.assert_not_called()
            self.assertFalse(
                (root / "clawshelf" / "clawshelf-brief.md").exists()
            )

    def _case_validation_failure_defers_without_p2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "note.md"
            source.write_text("standalone note", encoding="utf-8")
            result_item = Namespace(
                source=source,
                status="validation_failed",
                record_path=None,
                coverage="none",
                warnings=[
                    "paper_role.evidence must include source evidence"
                ],
            )
            with patch(
                "clawshelf.watch.stable_files",
                return_value=[source.resolve()],
            ), patch(
                "clawshelf.watch.normalize_sources",
                return_value=[result_item],
            ):
                _event_path, event = handle_files(root, [source])

            self.assertEqual(event["status"], "intake_deferred")
            self.assertIsNone(event["classification"])
            self.assertIsNone(event["priority"])
            self.assertEqual(
                event["normalization_outcomes"][0]["status"],
                "validation_failed",
            )

    def _case_partial_normalization_is_a_successful_intake(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "long-paper.md"
            source.write_text("source text", encoding="utf-8")
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            record = normalized / "long-paper.md"
            record.write_text(_normalized_record("long-paper.md", "trading agent benchmark"), encoding="utf-8")
            warning = "Section input exceeded the 24000-character budget; selected 4 of 12 sections and omitted 8."
            result_item = Namespace(
                source=source,
                record_path=record,
                status="normalized",
                coverage="partial",
                warnings=[warning],
            )
            with patch("clawshelf.watch.stable_files", return_value=[source.resolve()]), patch(
                "clawshelf.watch.normalize_sources",
                return_value=[result_item],
            ):
                result = handle_files(root, [source])

            self.assertIsNotNone(result)
            _event_path, event = result
            self.assertNotIn("normalization 未完成", event["reason"])
            self.assertEqual(event["normalization_outcomes"][0]["coverage"], "partial")
            self.assertEqual(
                event["normalization_outcomes"][0]["key_arguments"],
                [
                    "trading agent benchmark is central to the source "
                    "(source: `long-paper.md`, p. 1)."
                ],
            )
            self.assertTrue(any(item.endswith(warning) for item in event["normalization_warnings"]))

    def _case_startup_reconciliation_processes_stale_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = [root / "old.md"]
            stale[0].write_text("source text", encoding="utf-8")
            emitted = []
            with patch("clawshelf.watch.stale_sources", return_value=stale), patch(
                "clawshelf.watch.handle_files",
                return_value=(root / "clawshelf" / "events" / "event.json", {"priority": "P2"}),
            ) as handle:
                _reconcile_startup(root, None, "host_decides", emitted.append, None, None, None)

            handle.assert_called_once()
            self.assertEqual(handle.call_args.args[1], stale)
            self.assertEqual(len(emitted), 1)

    def _case_openclaw_notification_notifies_p1_and_p2_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "note.md"
            source.write_text("standalone note", encoding="utf-8")
            p1 = {
                "priority": "P1",
                "reason": "strong link",
                "new_files": [str(source)],
                "linked_sources": [],
                "idea_spark": "new idea",
                "push_target": "host_decides",
            }
            p2 = {**p1, "priority": "P2", "idea_spark": ""}
            p1_notification = build_notification(root / "p1.json", p1)
            p2_notification = build_notification(root / "p2.json", p2)
            self.assertEqual(p1_notification["schema"], NOTIFICATION_SCHEMA)
            self.assertTrue(p1_notification["enabled"])
            self.assertEqual(p1_notification["delivery"], "owner_dm")
            self.assertEqual(p1_notification["router"], "openclaw_delivery_turn")
            self.assertNotIn("openclaw_agent", json.dumps(p1_notification))
            self.assertTrue(p2_notification["enabled"])
            self.assertEqual(p2_notification["status"], "pending")
            self.assertEqual(p2_notification["policy"]["p2"], "deliver")
            p1_only_notification = build_notification(root / "p2-p1-only.json", p2, "p1_only")
            self.assertFalse(p1_only_notification["enabled"])
            self.assertEqual(p1_only_notification["status"], "log_only")

    def _case_openclaw_notification_message_uses_markdown_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "new-paper.pdf"
            record = root / "clawshelf" / "normalized" / "existing-record.md"
            event = {
                "priority": "P1",
                "reason": "New source has strong overlap with existing shelf records.",
                "new_files": [str(source)],
                "linked_sources": [
                    {
                        "new_source_path": str(source),
                        "linked_source_path": str(root / "existing-paper.pdf"),
                        "normalized_record_path": str(record),
                        "score": 18,
                        "matched_terms": ["retail cash flows", "momentum"],
                        "idea_candidates": [
                            {
                                "idea_type": "innovation",
                                "new_signal_type": "Strong Method",
                                "linked_signal_type": "Extension Hint",
                                "new_signal": "Estimate retail cash-flow pressure.",
                                "linked_signal": "Extend the momentum benchmark.",
                                "new_evidence": "p. 1 abstract",
                                "linked_evidence": "pp. 6-9 results",
                                "total_score": 18,
                            }
                        ],
                        "matched_evidence": [
                            {
                                "signal": "retail cash flows",
                                "new_evidence": "p. 1 abstract",
                                "linked_evidence": "pp. 6-9 results",
                                "why_it_matters": "evidence-backed topic match",
                            }
                        ],
                    }
                ],
                "synthesis_brief_update": {
                    "status": "updated",
                    "path": str(root / "clawshelf" / "clawshelf-brief.md"),
                    "new_connections": 1,
                    "candidate_ideas": 1,
                    "error": "",
                },
            }

            notification = build_notification(root / "p1.json", event)

        message = notification["message"]
        self.assertIn("**P1 ClawShelf：发现潜在研究连接**", message)
        self.assertIn("**新来源**\n`new-paper.pdf`", message)
        self.assertIn("**为什么推送**", message)
        self.assertIn("**可能相关的来源**", message)
        self.assertIn("- `existing-paper.pdf`", message)
        self.assertIn("**匹配信号**", message)
        self.assertIn("**1. 连接**\nretail cash flows", message)
        self.assertIn("新来源：`new-paper.pdf` p. 1 abstract", message)
        self.assertIn("关联来源：`existing-paper.pdf` pp. 6-9 results", message)
        self.assertIn("关系：evidence-backed topic match", message)
        self.assertIn("**Synthesis Brief**", message)
        self.assertIn("已自动更新 `clawshelf/clawshelf-brief.md`", message)
        self.assertIn("**候选 Ideas**", message)
        self.assertIn("[创新] Strong Method → Extension Hint", message)
        self.assertIn("总分：18", message)
        self.assertNotIn("建议下一步", message)
        self.assertNotIn("existing-record.md", message)
        self.assertNotIn("Linked records:", message)
        self.assertNotIn("Next:", message)

    def _case_openclaw_notification_maps_multiple_new_sources(self) -> None:
        event = {
            "priority": "P1",
            "new_files": ["/tmp/new-a.pdf", "/tmp/new-b.xlsx"],
            "linked_sources": [
                {
                    "new_source_path": "/tmp/new-a.pdf",
                    "linked_source_path": "/tmp/existing-a.pdf",
                    "normalized_record_path": "/tmp/clawshelf/normalized/existing-a.md",
                    "matched_evidence": [
                        {
                            "signal": "first connection",
                            "new_evidence": "section: A",
                            "linked_evidence": "section: B",
                            "why_it_matters": "first relation",
                        }
                    ],
                },
                {
                    "new_source_path": "/tmp/new-b.xlsx",
                    "linked_source_path": "/tmp/existing-b.csv",
                    "normalized_record_path": "/tmp/clawshelf/normalized/existing-b.md",
                    "matched_evidence": [
                        {
                            "signal": "second connection",
                            "new_evidence": "sheet: Inputs",
                            "linked_evidence": "rows: 4-8",
                            "why_it_matters": "second relation",
                        }
                    ],
                },
            ],
        }

        message = build_notification(Path("/tmp/p1.json"), event)["message"]

        self.assertIn("新来源：`new-a.pdf` section: A", message)
        self.assertIn("关联来源：`existing-a.pdf` section: B", message)
        self.assertIn("新来源：`new-b.xlsx` sheet: Inputs", message)
        self.assertIn("关联来源：`existing-b.csv` rows: 4-8", message)
        self.assertNotIn("existing-a.md", message)
        self.assertNotIn("existing-b.md", message)

    def _case_openclaw_notification_preserves_linked_url(self) -> None:
        url = "https://example.com/research/source?id=42"
        event = {
            "priority": "P1",
            "new_files": ["/tmp/new-paper.pdf"],
            "linked_sources": [
                {
                    "new_source_path": "/tmp/new-paper.pdf",
                    "linked_source_path": url,
                    "normalized_record_path": "/tmp/clawshelf/normalized/web-source.md",
                    "matched_evidence": [
                        {
                            "signal": "web connection",
                            "new_evidence": "section: Results",
                            "linked_evidence": "URL paragraph 3",
                            "why_it_matters": "source-backed web relation",
                        }
                    ],
                }
            ],
        }

        message = build_notification(Path("/tmp/p1.json"), event)["message"]

        self.assertIn(f"- `{url}`", message)
        self.assertIn(f"关联来源：`{url}` URL paragraph 3", message)
        self.assertNotIn("web-source.md", message)

    def _case_openclaw_notification_falls_back_to_compact_keywords(self) -> None:
        event = {
            "priority": "P1",
            "new_files": ["/tmp/new-paper.pdf"],
            "linked_sources": [
                {
                    "new_source_path": "/tmp/new-paper.pdf",
                    "linked_source_path": "/tmp/existing-paper.pdf",
                    "normalized_record_path": "/tmp/clawshelf/normalized/existing-record.md",
                    "matched_terms": ["retail cash flows", "momentum"],
                    "matched_evidence": [],
                }
            ],
        }

        message = build_notification(Path("/tmp/p1.json"), event)["message"]

        self.assertIn("候选关键词：`retail cash flows` · `momentum`", message)
        self.assertNotIn("- `retail cash flows`", message)

    def _case_p1_notification_reports_brief_failure(self) -> None:
        event = {
            "priority": "P1",
            "new_files": ["/tmp/new-paper.pdf"],
            "linked_sources": [
                {
                    "new_source_path": "/tmp/new-paper.pdf",
                    "linked_source_path": "/tmp/existing-paper.pdf",
                    "normalized_record_path": "/tmp/clawshelf/normalized/existing.md",
                    "matched_evidence": [
                        {
                            "signal": "evidence connection",
                            "new_evidence": "section: New",
                            "linked_evidence": "section: Existing",
                            "why_it_matters": "source-backed relation",
                        }
                    ],
                }
            ],
            "synthesis_brief_update": {
                "status": "failed",
                "path": "/tmp/clawshelf/clawshelf-brief.md",
                "new_connections": 0,
                "candidate_ideas": 0,
                "error": "brief is read-only",
            },
        }

        message = build_notification(Path("/tmp/p1.json"), event)["message"]

        self.assertIn("**Synthesis Brief**\n自动更新失败：brief is read-only", message)
        self.assertIn("**候选 Ideas**", message)
        self.assertNotIn("建议下一步", message)

    def _case_p1_notification_caps_ideas_at_three(self) -> None:
        candidates = []
        for index, idea_type in enumerate(
            ("innovation", "consolidation", "relation_candidate", "relation_candidate"),
            start=1,
        ):
            candidates.append(
                {
                    "idea_type": idea_type,
                    "new_signal_type": f"New Type {index}",
                    "linked_signal_type": f"Linked Type {index}",
                    "new_signal": f"new signal {index}",
                    "linked_signal": f"linked signal {index}",
                    "new_evidence": f"section: New {index}",
                    "linked_evidence": f"section: Linked {index}",
                    "total_score": 20 - index,
                }
            )
        event = {
            "priority": "P1",
            "new_files": ["/tmp/new-paper.pdf"],
            "linked_sources": [
                {
                    "new_source_path": "/tmp/new-paper.pdf",
                    "linked_source_path": "/tmp/existing-paper.pdf",
                    "normalized_record_path": "/tmp/clawshelf/normalized/existing.md",
                    "idea_candidates": candidates,
                    "matched_evidence": [],
                }
            ],
            "synthesis_brief_update": {
                "status": "updated",
                "new_connections": 1,
                "candidate_ideas": 3,
            },
        }

        message = build_notification(Path("/tmp/p1.json"), event)["message"]

        self.assertIn("**1. [创新]", message)
        self.assertIn("**2. [巩固]", message)
        self.assertIn("**3. [关系候选]", message)
        self.assertNotIn("**4. [", message)

    def _case_p2_notification_does_not_claim_a_research_connection(self) -> None:
        record_path = "/tmp/clawshelf/normalized/new-paper.md"
        event = {
            "priority": "P2",
            "reason": "新来源已进入 intake，但没有发现足够强的跨记录连接。",
            "new_files": ["/tmp/new-paper.pdf"],
            "linked_sources": [],
            "recommended_next_action": "保持索引即可；不需要主动推送。",
            "normalization_outcomes": [
                {
                    "source": "/tmp/new-paper.pdf",
                    "status": "normalized",
                    "record_path": record_path,
                    "key_arguments": [
                        "The structural model outperforms the baseline.",
                        "Performance depends on sufficient liquidity.",
                    ],
                }
            ],
        }

        message = build_notification(Path("/tmp/p2.json"), event)["message"]

        self.assertIn("**P2 ClawShelf：新来源已完成入库**", message)
        self.assertIn("**新来源**\n`new-paper.pdf`", message)
        self.assertNotIn("/tmp/new-paper.pdf", message)
        self.assertNotIn(record_path, message)
        self.assertNotIn("**归档记录**", message)
        self.assertIn("**关键论点（来自 Normalization）**", message)
        self.assertIn("**`new-paper.pdf`**", message)
        self.assertIn(
            "- The structural model outperforms the baseline.",
            message,
        )
        self.assertIn("- Performance depends on sufficient liquidity.", message)
        self.assertNotIn("发现潜在研究连接", message)
        self.assertNotIn("可能相关的来源", message)
        self.assertNotIn("匹配信号", message)
        self.assertNotIn("建议下一步", message)

    def _case_p2_notification_groups_multiple_sources(self) -> None:
        event = {
            "priority": "P2",
            "new_files": ["/tmp/first.pdf", "/tmp/second.xlsx"],
            "linked_sources": [],
            "normalization_outcomes": [
                {
                    "source": "/tmp/first.pdf",
                    "record_path": "/tmp/clawshelf/normalized/first.md",
                    "key_arguments": ["First source argument."],
                },
                {
                    "source": "/tmp/second.xlsx",
                    "record_path": "/tmp/clawshelf/normalized/second.md",
                    "key_arguments": ["Second source argument."],
                },
            ],
        }

        message = build_notification(Path("/tmp/p2.json"), event)["message"]

        self.assertIn("**新来源**\n`first.pdf`\n`second.xlsx`", message)
        self.assertIn("**`first.pdf`**\n- First source argument.", message)
        self.assertIn("**`second.xlsx`**\n- Second source argument.", message)
        self.assertNotIn("first.md", message)
        self.assertNotIn("second.md", message)

    def _case_openclaw_notification_message_shows_creativity_reason(self) -> None:
        root = Path("/tmp/clawshelf-test")
        event = {
            "priority": "P1",
            "reason": "creativity score passed",
            "new_files": [str(root / "new-paper.pdf")],
            "linked_sources": [
                {
                    "new_source_path": str(root / "new-paper.pdf"),
                    "linked_source_path": str(root / "existing-paper.pdf"),
                    "normalized_record_path": str(root / "existing-record.md"),
                    "score": 14,
                    "matched_terms": ["execution benchmark link"],
                    "matched_evidence": [
                        {
                            "signal": "execution benchmark link",
                            "new_evidence": "new summary",
                            "linked_evidence": "linked methods",
                            "why_it_matters": "both evaluate trading agents",
                        }
                    ],
                }
            ],
        }

        message = build_notification(root / "p1.json", event)["message"]

        self.assertIn("**1. 连接**\nexecution benchmark link", message)
        self.assertIn("both evaluate trading agents", message)

    def _case_notification_is_persisted_under_clawshelf_notifications(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_path = root / "clawshelf" / "events" / "20260722-p1.json"
            event_path.parent.mkdir(parents=True)
            notification = {
                "schema": NOTIFICATION_SCHEMA,
                "enabled": True,
                "status": "pending",
                "message": "hello",
            }
            path = write_notification(event_path, notification)
            self.assertEqual(path.parent, root / "clawshelf" / "notifications")
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "pending")

    def _case_delivery_binds_session_key_and_provider_channel(self) -> None:
        notification = {
            "schema": NOTIFICATION_SCHEMA,
            "enabled": True,
            "message": "P1 ClawShelf notification",
        }
        with patch("openclaw_watch_adapter.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            receipt = deliver_notification(
                notification,
                agent_id="agent-test",
                channel="feishu",
                session_key="agent:agent-test:feishu:agent-test:direct:ou_123",
            )

        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["openclaw", "agent", "--agent", "agent-test"])
        self.assertIn("--deliver", command)
        self.assertIn("--session-key", command)
        self.assertIn("agent:agent-test:feishu:agent-test:direct:ou_123", command)
        self.assertIn("--channel", command)
        self.assertIn("feishu", command)
        self.assertIn("--reply-channel", command)
        self.assertIn("--reply-to", command)
        self.assertIn("user:ou_123", command)
        self.assertIn("--reply-account", command)
        self.assertIn("agent-test", command)
        self.assertNotIn("telegram", command)
        self.assertEqual(receipt["status"], "turn_succeeded")
        self.assertEqual(receipt["delivery_mode"], "session_key")
        self.assertEqual(receipt["agent_id"], "agent-test")

    def _case_delivery_falls_back_to_channel_without_session_key(self) -> None:
        notification = {
            "schema": NOTIFICATION_SCHEMA,
            "enabled": True,
            "message": "P1 ClawShelf notification",
        }
        with patch("openclaw_watch_adapter.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            receipt = deliver_notification(notification, agent_id="agent-test", channel="last")

        command = run.call_args.args[0]
        self.assertIn("--channel", command)
        self.assertIn("last", command)
        self.assertNotIn("--session-key", command)
        self.assertEqual(receipt["status"], "turn_succeeded")
        self.assertEqual(receipt["delivery_mode"], "channel")

    def _case_delivery_missing_binary_and_timeout_return_failed(self) -> None:
        notification = {"enabled": True, "message": "hello"}
        with patch("openclaw_watch_adapter.shutil.which", return_value=None):
            missing = deliver_notification(notification, openclaw_bin="missing-openclaw")
        self.assertEqual(missing["status"], "failed")

        with patch("openclaw_watch_adapter.shutil.which", return_value="/bin/openclaw"), patch(
            "openclaw_watch_adapter.subprocess.run",
            side_effect=__import__("subprocess").TimeoutExpired(["openclaw"], 120),
        ):
            timed_out = deliver_notification(notification)
        self.assertEqual(timed_out["status"], "failed")

    def _case_no_deliver_notification_is_not_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / "clawshelf" / "events"
            events.mkdir(parents=True)
            source = root / "note.md"
            source.write_text("source", encoding="utf-8")
            event_path = events / "p2.json"
            event = {
                "priority": "P2",
                "new_files": [str(source)],
                "normalization_outcomes": [],
            }

            with patch("builtins.print"):
                _handle_result(
                    (event_path, event),
                    "p1_p2",
                    False,
                    None,
                    "last",
                    None,
                    "openclaw",
                )
            notification_path = (
                root
                / "clawshelf"
                / "notifications"
                / "p2.notification.json"
            )
            notification = json.loads(
                notification_path.read_text(encoding="utf-8")
            )
            with patch(
                "openclaw_watch_adapter.deliver_notification"
            ) as deliver:
                retry_pending_notifications(root)

            self.assertEqual(
                notification["status"],
                "delivery_disabled",
            )
            deliver.assert_not_called()

    def _case_notification_ledger_suppresses_identical_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "note.md"
            source.write_text("same bytes", encoding="utf-8")
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            record = normalized / "note.md"
            record.write_text(_normalized_record("note.md", "retail cash flows"), encoding="utf-8")
            events = root / "clawshelf" / "events"
            events.mkdir()
            event = {"priority": "P1", "new_files": [str(source)], "linked_sources": [], "reason": "link"}

            with patch(
                "openclaw_watch_adapter.deliver_notification",
                return_value={"status": "turn_succeeded"},
            ) as deliver, patch("builtins.print"):
                first_path = events / "first-p1.json"
                second_path = events / "second-p1.json"
                _handle_result((first_path, event), False, True, None, "last", None, "openclaw")
                _handle_result((second_path, event), False, True, None, "last", None, "openclaw")
                record.write_text(
                    _normalized_record("note.md", "retail cash flows").replace(
                        "source_sha256: abc123", "source_sha256: changed456"
                    ),
                    encoding="utf-8",
                )
                third_path = events / "third-p1.json"
                _handle_result((third_path, {**event, "status": ""}), False, True, None, "last", None, "openclaw")
                p2_event = {**event, "priority": "P2", "reason": "stored"}
                first_p2_path = events / "first-p2.json"
                second_p2_path = events / "second-p2.json"
                _handle_result((first_p2_path, p2_event), "p1_p2", True, None, "last", None, "openclaw")
                _handle_result((second_p2_path, p2_event), "p1_p2", True, None, "last", None, "openclaw")

            self.assertEqual(deliver.call_count, 3)
            notification = json.loads(
                (root / "clawshelf" / "notifications" / "second-p1.notification.json").read_text(encoding="utf-8")
            )
            self.assertEqual(notification["status"], "suppressed_duplicate")
            changed = json.loads(
                (root / "clawshelf" / "notifications" / "third-p1.notification.json").read_text(encoding="utf-8")
            )
            self.assertEqual(changed["status"], "turn_succeeded")
            p2_duplicate = json.loads(
                (root / "clawshelf" / "notifications" / "second-p2.notification.json").read_text(encoding="utf-8")
            )
            self.assertEqual(p2_duplicate["status"], "suppressed_duplicate")

    def _case_pending_retry_is_capped_at_three_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notifications = root / "clawshelf" / "notifications"
            notifications.mkdir(parents=True)
            path = notifications / "event.notification.json"
            path.write_text(
                json.dumps({
                    "enabled": True,
                    "status": "failed",
                    "attempts": 2,
                    "message": "hello",
                    "policy": {"channel": "last"},
                }),
                encoding="utf-8",
            )
            with patch("openclaw_watch_adapter.deliver_notification", return_value={"status": "failed"}) as deliver:
                retry_pending_notifications(root)
                retry_pending_notifications(root)
            self.assertEqual(deliver.call_count, 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["attempts"], 3)

    def _case_failed_notification_retries_after_route_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notifications = root / "clawshelf" / "notifications"
            notifications.mkdir(parents=True)
            path = notifications / "event.notification.json"
            path.write_text(
                json.dumps({
                    "enabled": True,
                    "status": "failed",
                    "attempts": 3,
                    "message": "hello",
                    "session_key": "agent:agent-test:feishu:direct:user",
                    "policy": {
                        "agent_id": "old-agent",
                        "channel": "last",
                        "session_key": "agent:agent-test:feishu:direct:user",
                    },
                }),
                encoding="utf-8",
            )
            with patch(
                "openclaw_watch_adapter.deliver_notification",
                return_value={"status": "turn_succeeded"},
            ) as deliver:
                retry_pending_notifications(
                    root,
                    agent_id="agent-test",
                    channel="feishu",
                    session_key="agent:agent-test:feishu:direct:user",
                )

            deliver.assert_called_once()
            self.assertEqual(deliver.call_args.args[1], "agent-test")
            notification = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(notification["status"], "turn_succeeded")
            self.assertEqual(notification["attempts"], 1)
            self.assertEqual(notification["policy"]["agent_id"], "agent-test")
            self.assertEqual(notification["policy"]["channel"], "feishu")

    def _case_scratch_p1_and_p2_watch_adapter_directives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "existing-retail-flow.md").write_text(
                _normalized_record("existing.md", "retail cash flows"),
                encoding="utf-8",
            )
            p1_source = root / "new-retail-flow-note.md"
            p1_source.write_text(
                "retail cash flows investor heterogeneity Hurst exponent detrended fluctuation analysis "
                "market volatility prediction Korean equity market persistence regime sensitivity "
                "institutional net flows future volatility",
                encoding="utf-8",
            )
            (normalized / "new-retail-flow-note.md").write_text(
                _normalized_record("new-retail-flow-note.md", "retail cash flows"),
                encoding="utf-8",
            )
            p2_source = root / "new-unrelated-note.md"
            p2_source.write_text(
                "ceramic kiln glaze pottery studio shelf firing workshop clay bowl",
                encoding="utf-8",
            )
            (normalized / "new-unrelated-note.md").write_text(
                _normalized_record("new-unrelated-note.md", "ceramic kiln glaze"),
                encoding="utf-8",
            )

            with patch("clawshelf.watch.stable_files", side_effect=lambda paths: paths), patch("clawshelf.watch.normalize_sources", return_value=[]):
                p1_path, p1_event = handle_files(root, [p1_source])
                p2_path, p2_event = handle_files(root, [p2_source])

            self.assertEqual(p1_event["priority"], "P1")
            self.assertEqual(p2_event["priority"], "P2")
            self.assertTrue(build_notification(p1_path, p1_event)["enabled"])
            self.assertTrue(build_notification(p2_path, p2_event)["enabled"])
            self.assertFalse(build_notification(p2_path, p2_event, "p1_only")["enabled"])


if __name__ == "__main__":
    unittest.main()
