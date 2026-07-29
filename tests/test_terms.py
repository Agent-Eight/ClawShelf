from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.normalize import RagTerm
from clawshelf.terms import is_generic_term, match_rag_terms, normalize_term, terms_match


class TermsTests(unittest.TestCase):
    def test_normalize_term(self) -> None:
        self.assertEqual(normalize_term("Retail Cash-Flows!"), "retail cash flow")
        self.assertEqual(normalize_term("  Volatility   Prediction  "), "volatility prediction")

    def test_generic_terms_are_filtered(self) -> None:
        self.assertTrue(is_generic_term("abstract"))
        self.assertTrue(is_generic_term("market"))
        self.assertTrue(is_generic_term("研究"))
        self.assertFalse(is_generic_term("retail cash flows"))
        self.assertFalse(is_generic_term("volatility prediction"))

    def test_aliases_match(self) -> None:
        left = RagTerm(
            term="retail cash flows",
            weight=5,
            aliases=["retail order flow"],
            evidence="p. 1",
            role="topic",
        )
        right = RagTerm(
            term="household flow",
            weight=4,
            aliases=["retail order flow"],
            evidence="p. 6",
            role="topic",
        )
        self.assertTrue(terms_match(left, right))

    def test_meaningful_multiword_containment_matches(self) -> None:
        left = RagTerm(
            term="reinforcement learning",
            weight=5,
            aliases=[],
            evidence="p. 2",
            role="method",
        )
        right = RagTerm(
            term="deep reinforcement learning for algorithmic trading",
            weight=5,
            aliases=["DRL trading"],
            evidence="p. 1 abstract",
            role="topic",
        )
        self.assertTrue(terms_match(left, right))

    def test_match_rag_terms_scores_specific_terms(self) -> None:
        new_terms = [
            RagTerm("abstract", 5, [], "p. 1", "topic"),
            RagTerm("volatility prediction", 5, ["future volatility"], "pp. 9-11", "finding"),
        ]
        existing_terms = [
            RagTerm("future volatility", 4, ["volatility prediction"], "p. 8", "finding"),
            RagTerm("market", 5, [], "p. 1", "topic"),
        ]
        matches = match_rag_terms(new_terms, existing_terms)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].term, "volatility prediction")
        self.assertGreater(matches[0].score, 10)


if __name__ == "__main__":
    unittest.main()
