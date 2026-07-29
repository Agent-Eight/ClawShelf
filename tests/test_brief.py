from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.brief import (
    MANAGED_END,
    MANAGED_START,
    BriefUpdateError,
    select_candidate_ideas,
    update_synthesis_brief,
)
from clawshelf.config import ShelfConfig


class BriefTests(unittest.TestCase):
    def test_update_preserves_manual_content_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clawshelf = root / "clawshelf"
            normalized = clawshelf / "normalized"
            normalized.mkdir(parents=True)
            (normalized / "new.md").write_text("record", encoding="utf-8")
            brief = clawshelf / "clawshelf-brief.md"
            brief.write_text(
                "# Existing Brief\n\n## Manual Analysis\n\nKeep this paragraph.\n",
                encoding="utf-8",
            )
            config = ShelfConfig(
                shelf_plan={
                    "domain_background": "financial research",
                    "work_direction": "idea discovery",
                    "concrete_problem": "find robust edges",
                    "companion_mode": "research assistant",
                }
            )
            event = _p1_event()

            first = update_synthesis_brief(root, event, config)
            first_text = brief.read_text(encoding="utf-8")
            second = update_synthesis_brief(root, event, config)
            second_text = brief.read_text(encoding="utf-8")

            self.assertEqual(first.status, "updated")
            self.assertEqual(first.new_connections, 1)
            self.assertEqual(first.candidate_ideas, 3)
            self.assertEqual(second.status, "unchanged")
            self.assertEqual(second.new_connections, 0)
            self.assertEqual(first_text, second_text)
            self.assertIn("Keep this paragraph.", first_text)
            self.assertEqual(first_text.count(MANAGED_START), 1)
            self.assertEqual(first_text.count(MANAGED_END), 1)
            self.assertIn("new-paper.pdf", first_text)
            self.assertIn("existing-paper.pdf", first_text)
            self.assertNotIn("existing-record.md", first_text)

    def test_select_candidate_ideas_prefers_structured_and_caps_at_three(self) -> None:
        ideas = select_candidate_ideas(_p1_event(), limit=3)

        self.assertEqual(len(ideas), 3)
        self.assertEqual(
            [item["idea_type"] for item in ideas],
            ["innovation", "consolidation", "relation_candidate"],
        )
        self.assertTrue(all(item["new_source_path"].endswith("new-paper.pdf") for item in ideas))
        self.assertTrue(
            all(item["linked_source_path"].endswith("existing-paper.pdf") for item in ideas)
        )

    def test_select_candidate_ideas_fills_from_matched_evidence(self) -> None:
        event = _p1_event()
        event["linked_sources"][0]["idea_candidates"] = event["linked_sources"][0][
            "idea_candidates"
        ][:1]

        ideas = select_candidate_ideas(event, limit=3)

        self.assertEqual(len(ideas), 3)
        self.assertEqual(ideas[0]["idea_type"], "innovation")
        self.assertEqual(
            [item["idea_type"] for item in ideas[1:]],
            ["connection_candidate", "connection_candidate"],
        )

    def test_incomplete_managed_region_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clawshelf = root / "clawshelf"
            clawshelf.mkdir()
            (clawshelf / "clawshelf-brief.md").write_text(
                f"# Brief\n\n{MANAGED_START}\n",
                encoding="utf-8",
            )

            with self.assertRaises(BriefUpdateError):
                update_synthesis_brief(root, _p1_event(), ShelfConfig())


def _p1_event() -> dict:
    candidates = [
        _idea("innovation", "Strong Method", "Extension Hint", 18),
        _idea("consolidation", "Strong Limitation", "Failure Mode", 17),
        _idea("relation_candidate", "Assumption", "Metric Choice", 16),
        _idea("relation_candidate", "Strong Method", "Metric Choice", 15),
    ]
    return {
        "schema": "clawshelf.watch-event",
        "created_at": "2026-07-26T05:00:00+00:00",
        "priority": "P1",
        "reason": "P1 gates passed.",
        "new_files": ["/tmp/new-paper.pdf"],
        "linked_sources": [
            {
                "new_source_path": "/tmp/new-paper.pdf",
                "linked_source_path": "/tmp/existing-paper.pdf",
                "normalized_record_path": "/tmp/clawshelf/normalized/existing-record.md",
                "creativity_score": 18,
                "confidence": 0.8,
                "idea_candidates": candidates,
                "matched_evidence": [
                    {
                        "signal": "first evidence connection",
                        "new_evidence": "section: New A",
                        "linked_evidence": "section: Linked A",
                        "why_it_matters": "first relation",
                    },
                    {
                        "signal": "second evidence connection",
                        "new_evidence": "section: New B",
                        "linked_evidence": "section: Linked B",
                        "why_it_matters": "second relation",
                    },
                ],
            }
        ],
    }


def _idea(
    idea_type: str,
    new_type: str,
    linked_type: str,
    total_score: int,
) -> dict:
    return {
        "idea_type": idea_type,
        "new_signal_type": new_type,
        "linked_signal_type": linked_type,
        "new_signal": f"{new_type} signal",
        "linked_signal": f"{linked_type} signal",
        "new_evidence": "section: New",
        "linked_evidence": "section: Linked",
        "overlap_score": 3,
        "complementarity_score": 5,
        "novelty_score": 4,
        "evidence_score": 4,
        "feasibility_score": 2,
        "total_score": total_score,
    }


if __name__ == "__main__":
    unittest.main()
