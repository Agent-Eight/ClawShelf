from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.idea import (
    _overlap_score,
    content_terms,
    generate_idea_candidates,
    generate_relation_candidates,
    overlap_from_terms,
    score_signal_pair,
    score_signal_pair_with_terms,
)
from clawshelf.normalize import NormalizedRecord, SignalEntry
from clawshelf.terms import bridge_concepts


def _signal(signal_type: str, signal: str, evidence: str = "p. 1") -> SignalEntry:
    return SignalEntry(type=signal_type, signal=signal, evidence=evidence, raw={})


class IdeaTests(unittest.TestCase):
    def test_overlap_from_terms_matches_overlap_score(self) -> None:
        """Pin the pre-computed-terms path against the string path it replaced."""
        pairs = [
            # identical -> ratio 1.0
            ("battery degradation forecast", "battery degradation forecast"),
            # high ratio
            (
                "retail flow volatility prediction is single market evidence",
                "retail flow volatility prediction may fail outside single samples",
            ),
            # partial ratio
            (
                "graph neural network forecasts battery degradation",
                "battery degradation forecasts fail under cold temperature",
            ),
            # low ratio
            (
                "community monitoring supports river restoration outcomes",
                "river restoration needs an explicit outcome metric",
            ),
            # no shared terms, but _nearby_terms containment applies
            ("shared monitoring data", "shared monitoring data platform design"),
            # fully disjoint
            ("battery degradation forecast", "community river restoration"),
            # empty / generic-only sides
            ("", "battery degradation forecast"),
            ("paper research method", "paper research method"),
        ]

        for left, right in pairs:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    overlap_from_terms(content_terms(left), content_terms(right)),
                    _overlap_score(left, right),
                )

    def test_score_signal_pair_with_terms_matches_the_string_entrypoint(self) -> None:
        left = _signal("Strong Method", "graph neural network forecasts battery degradation")
        right = _signal("Strong Limitation", "battery degradation forecasts fail under cold temperature")

        self.assertEqual(
            score_signal_pair_with_terms(
                left,
                right,
                content_terms(left.signal),
                content_terms(right.signal),
            ),
            score_signal_pair(left, right),
        )

    def test_bridge_concepts_require_two_non_generic_terms(self) -> None:
        concepts = bridge_concepts(
            ["- use", "features and", "fail to", "prediction market execution"]
        )

        self.assertNotIn("use", concepts)
        self.assertNotIn("features and", concepts)
        self.assertNotIn("fail to", concepts)
        self.assertIn("prediction market", concepts)

    def test_classifies_innovation_when_method_complements_limitation_with_partial_overlap(self) -> None:
        candidate = score_signal_pair(
            _signal("Strong Method", "graph neural network forecasts battery degradation"),
            _signal("Strong Limitation", "battery degradation forecasts fail under cold temperature"),
        )

        self.assertEqual(candidate.idea_type, "innovation")
        self.assertGreaterEqual(candidate.complementarity_score, 4)
        self.assertGreaterEqual(candidate.novelty_score, 3)

    def test_classifies_consolidation_when_overlap_is_high_but_not_identical(self) -> None:
        candidate = score_signal_pair(
            _signal("Strong Limitation", "retail flow volatility prediction is single market evidence"),
            _signal("Failure Mode", "retail flow volatility prediction may fail outside single market samples"),
        )

        self.assertEqual(candidate.idea_type, "consolidation")
        self.assertGreaterEqual(candidate.overlap_score, 4)

    def test_rejects_weak_keyword_only_analogy(self) -> None:
        candidate = score_signal_pair(
            _signal("Strong Contribution", "paper research method"),
            _signal("Strong Limitation", "paper research method"),
        )

        self.assertEqual(candidate.idea_type, "reject")
        self.assertEqual(candidate.overlap_score, 0)

    def test_relation_candidates_do_not_require_a_rag_match(self) -> None:
        new = NormalizedRecord(
            frontmatter={},
            title="Arbitrage",
            sections={},
            axon_signals=[
                _signal(
                    "Strong Method",
                    "prediction market arbitrage screening under liquidity constraints",
                    "section: Arbitrage",
                )
            ],
        )
        linked = NormalizedRecord(
            frontmatter={},
            title="Benchmark",
            sections={},
            dendrite_signals=[
                _signal(
                    "Extension Hint",
                    "test prediction market execution with fees and settlement",
                    "section: Limitations",
                )
            ],
        )

        candidates = generate_relation_candidates(new, linked)

        self.assertTrue(candidates)
        self.assertTrue(candidates[0].new_evidence)
        self.assertTrue(candidates[0].linked_evidence)

    def test_relation_candidates_require_evidence_from_both_records(self) -> None:
        new = NormalizedRecord(
            frontmatter={},
            title="No evidence",
            sections={},
            axon_signals=[_signal("Strong Method", "prediction market execution", "")],
        )
        linked = NormalizedRecord(
            frontmatter={},
            title="Evidence",
            sections={},
            dendrite_signals=[
                _signal("Extension Hint", "prediction market execution", "section: Results")
            ],
        )

        self.assertEqual(generate_relation_candidates(new, linked), [])

    def test_evidence_backed_complementary_prefilter_keeps_nearby_relation(self) -> None:
        new = NormalizedRecord(
            frontmatter={},
            title="Arbitrage",
            sections={},
            axon_signals=[
                _signal(
                    "Strong Method",
                    "prediction-market arbitrage with execution constraints",
                    "section: Methods",
                )
            ],
        )
        linked = NormalizedRecord(
            frontmatter={},
            title="Benchmark",
            sections={},
            dendrite_signals=[
                _signal(
                    "Extension Hint",
                    "prediction markets benchmark agent settlement",
                    "section: Limitations",
                )
            ],
        )

        candidates = generate_idea_candidates(new, linked)

        self.assertTrue(candidates)
        self.assertIn(
            candidates[0].idea_type,
            {"innovation", "consolidation", "relation_candidate"},
        )


if __name__ == "__main__":
    unittest.main()
