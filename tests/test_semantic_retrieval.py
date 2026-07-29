from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.creativity_score import (
    CreativityCandidate,
    deterministic_score,
    merge_semantic_candidates,
)
from clawshelf.events import CreativityScoringOptions, classify_new_files
from clawshelf.normalize import NormalizedRecord
from clawshelf.semantic_retrieval import (
    SemanticHit,
    SemanticRetrievalResult,
    collection_name,
    parse_qmd_results,
    run_qmd_vector_retrieval,
)


def _record(source: str, title: str, term: str) -> str:
    return f"""---
source: {source}
source_type: md
source_sha256: abc123
extraction_method: text
confidence: High
---

# {title}

## Summary

{term} is evaluated with source-backed observations (source: `{source}`, p. 1).

## Keywords

- `{term}` — central source concept; evidence: p. 1

## RAG Terms

- term: {term}
  weight: 5
  aliases: none
  evidence: p. 1
  role: topic

## Key Claims

- {term} is central to this source (source: `{source}`, p. 1).

## Methods or Basis

Source-backed evaluation method (source: `{source}`, p. 2).

## Limitations

- Scope is limited to this source (source: `{source}`, p. 3).
"""


class SemanticRetrievalTests(unittest.TestCase):
    def test_collection_name_is_stable_and_shelf_specific(self) -> None:
        self.assertEqual(collection_name(Path("/tmp/a")), collection_name(Path("/tmp/a")))
        self.assertNotEqual(collection_name(Path("/tmp/a")), collection_name(Path("/tmp/b")))

    def test_qmd_json_parser_preserves_rank_and_similarity(self) -> None:
        rows = parse_qmd_results(
            json.dumps(
                [
                    {"file": "/tmp/first.md", "score": 0.82},
                    {"file": "/tmp/second.md", "score": 0.61},
                ]
            )
        )

        self.assertEqual(rows, [("/tmp/first.md", 0.82), ("/tmp/second.md", 0.61)])

    def test_qmd_adapter_excludes_the_query_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            new_path = normalized / "new.md"
            linked_path = normalized / "linked.md"
            new_path.write_text("# new", encoding="utf-8")
            linked_path.write_text("# linked", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                ["qmd"],
                0,
                json.dumps(
                    [
                        {"file": str(new_path), "score": 0.99},
                        {"file": str(linked_path), "score": 0.75},
                    ]
                ),
                "",
            )

            with (
                patch("clawshelf.semantic_retrieval.shutil.which", return_value="/bin/qmd"),
                patch("clawshelf.semantic_retrieval._ensure_collection"),
                patch("clawshelf.semantic_retrieval._run", return_value=completed),
            ):
                result = run_qmd_vector_retrieval(
                    root,
                    new_path,
                    NormalizedRecord({}, "new", {}),
                    [(linked_path, NormalizedRecord({}, "linked", {}))],
                    2,
                )

            self.assertEqual(result.status, "used")
            self.assertEqual([Path(hit.path).name for hit in result.hits], ["linked.md"])

    def test_vector_similarity_never_becomes_creativity_score(self) -> None:
        linked = NormalizedRecord({}, "linked", {})
        candidate = CreativityCandidate(
            linked_record_path="/tmp/linked.md",
            linked_record=linked,
            retrieval_path=["qmd_vector"],
            semantic_similarity=0.99,
        )

        score = deterministic_score(candidate)

        self.assertEqual(score.creativity_score, 3)
        self.assertEqual(score.verdict, "p2_intake")

    def test_merge_keeps_deterministic_order_then_qmd_rank(self) -> None:
        first = Path("/tmp/first.md")
        second = Path("/tmp/second.md")
        third = Path("/tmp/third.md")
        deterministic = CreativityCandidate(
            linked_record_path=str(first),
            linked_record=NormalizedRecord({}, "first", {}),
            retrieval_path=["rag_exact_or_alias"],
        )

        merged = merge_semantic_candidates(
            [deterministic],
            SemanticRetrievalResult(
                status="used",
                hits=[
                    SemanticHit(str(second), 0.8),
                    SemanticHit(str(third), 0.7),
                ],
            ),
            [
                (first, deterministic.linked_record),
                (second, NormalizedRecord({}, "second", {})),
                (third, NormalizedRecord({}, "third", {})),
            ],
            candidate_limit=3,
            novelty_preference=0.5,
        )

        self.assertEqual(
            [Path(candidate.linked_record_path).name for candidate in merged],
            ["first.md", "second.md", "third.md"],
        )

    def test_event_uses_qmd_to_fill_candidates_but_remains_p2_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            linked_path = normalized / "linked.md"
            new_path = normalized / "new.md"
            linked_path.write_text(
                _record("linked.md", "PredictionMarketBench", "execution benchmark"),
                encoding="utf-8",
            )
            new_path.write_text(
                _record("new.md", "QuantPedia", "inter-exchange arbitrage"),
                encoding="utf-8",
            )
            source = root / "new.md"
            source.write_text("source", encoding="utf-8")

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(
                    mode="off",
                    semantic_retrieval="auto",
                    semantic_candidate_target=3,
                    semantic_retriever=lambda *_: SemanticRetrievalResult(
                        status="used",
                        hits=[SemanticHit(str(linked_path), 0.84)],
                    ),
                ),
            )

            self.assertEqual(event.priority, "P2")
            self.assertEqual(event.creativity_score, 3)
            self.assertEqual(event.linked_sources[0].retrieval_path, ["qmd_vector"])
            self.assertEqual(event.linked_sources[0].semantic_similarity, 0.84)
            self.assertEqual(event.semantic_retrieval["status"], "used")

    def test_required_qmd_failure_defers_intake(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "new.md").write_text(
                _record("new.md", "New", "isolated topic"),
                encoding="utf-8",
            )
            source = root / "new.md"
            source.write_text("source", encoding="utf-8")

            event = classify_new_files(
                root,
                [source],
                creativity_options=CreativityScoringOptions(
                    semantic_retrieval="required",
                    semantic_retriever=lambda *_: SemanticRetrievalResult(
                        status="unavailable",
                        error="embedding model unavailable",
                    ),
                ),
            )

            self.assertEqual(event.status, "intake_deferred")
            self.assertIsNone(event.priority)
            self.assertEqual(event.semantic_retrieval["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
