from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.normalize import parse_normalized_record, validate_normalized_record


VALID_RECORD = """---
source: paper.pdf
source_type: pdf
source_sha256: abc123
extraction_method: pdf
confidence: High
shelf_plan_tags: financial research / quant trading
---

# Example Paper

## 总结

The paper studies retail cash-flow persistence in equity markets using daily investor-group flow data (source: `paper.pdf`, p. 1). It estimates Hurst exponents with detrended fluctuation analysis and rolling windows (source: `paper.pdf`, pp. 3-4). It finds retail flow persistence predicts future volatility, while noting the result is market- and sample-specific (source: `paper.pdf`, pp. 9-11).

## 文档在资料架中的作用

Map role: evidence / idea seed for retail-flow trading signals (source: `paper.pdf`, pp. 9-11).

## 研究问题

The paper asks whether retail cash-flow persistence reveals investor heterogeneity and predicts market dynamics (source: `paper.pdf`, p. 1).

## 方法 / 数据 / 场景

Daily investor-group flow data, detrended fluctuation analysis, rolling Hurst exponents, and volatility regressions in an equity-market setting (source: `paper.pdf`, pp. 3-11).

## 主题

- Retail cash flows
- Volatility prediction

## 关键词

- `retail cash flows` — central investor-flow variable; evidence: p. 1 abstract
- `Hurst exponent` — persistence measure; evidence: pp. 3-4 methods
- `detrended fluctuation analysis` — estimation method; evidence: pp. 3-4 methods
- `rolling windows` — time-varying analysis; evidence: p. 6 results
- `volatility prediction` — main predictive result; evidence: pp. 9-11 results
- `investor heterogeneity` — core framing; evidence: p. 1 introduction
- `Korean equity market` — dataset scope; evidence: p. 3 data
- `net flows` — key comparison variable; evidence: pp. 8-9 results

## RAG 术语

- term: retail cash flows
  weight: 5
  aliases: retail order flow; household flow
  evidence: p. 1 abstract
  role: topic
- term: Hurst exponent
  weight: 4
  aliases: long memory; persistence
  evidence: pp. 3-4 methods
  role: method
- term: volatility prediction
  weight: 5
  aliases: future volatility
  evidence: pp. 9-11 results
  role: finding

## 知识图谱标签

- Domain: financial research
- Problem fit: quant trading signal design
- Map role: method / evidence

## 关键论点

- Retail flow persistence predicts future volatility (source: `paper.pdf`, pp. 9-11).
- Hurst exponents differ across investor groups (source: `paper.pdf`, pp. 7-9).

## 方法或依据

Daily investor-group flow data, detrended fluctuation analysis, rolling Hurst exponents, and volatility regressions (source: `paper.pdf`, pp. 3-11).

## 局限性

### 使用条件

- category: Scope Boundaries
  limitation: The sample is tied to a single equity-market setting.
  implication: Use the finding as market-specific evidence rather than assuming cross-market generalization.
  evidence: p. 3 data

### 改进方向

- category: Generalization Limits
  direction: Replicate the analysis across additional markets, periods, and investor-group definitions.
  expected_value: The retail-flow signal would be more reliable for cross-market synthesis and idea generation.
  evidence_or_rationale: rationale: single-market evidence on p. 3 limits external validity

## 轴突信号

- type: Strong Contribution
  signal: Retail flow persistence is presented as a predictive signal for future volatility.
  evidence: pp. 9-11 results
- type: Strong Method
  signal: Detrended fluctuation analysis estimates rolling Hurst exponents.
  evidence: pp. 3-4 methods
- type: Strong Limitation
  signal: The sample is tied to one equity-market setting.
  evidence: p. 3 data
- type: Strong Application Method
  signal: Use investor-group flow persistence as a screening signal for volatility research.
  evidence: pp. 9-11 results

## 树突信号

- type: Assumption
  signal: Retail investor groups are separable enough for flow persistence to be meaningful.
  evidence: p. 1 introduction
- type: Data / Domain Boundary
  signal: The evidence comes from a Korean equity-market dataset.
  evidence: p. 3 data
- type: Metric Choice
  signal: Hurst exponents are used as the persistence metric.
  evidence: pp. 3-4 methods
- type: Failure Mode
  signal: Cross-market transfer may fail if investor-group definitions differ.
  evidence: rationale: single-market scope on p. 3
- type: Extension Hint
  signal: Replicate across additional markets and investor-group definitions.
  evidence: rationale: improvement direction from p. 3 scope

## 证据备注

- Original source: `paper.pdf`
- Title, abstract, and methods are on pages 1-4.

## 想法信号

- Compare retail flow persistence with execution-cost regimes; speculation grounded in pp. 9-11.

## 连接钩子

- `retail cash flows` (topic): connect to records about retail order flow and internalized trade imbalances (source: `paper.pdf`, p. 1).
- `volatility prediction` (finding): connect to records about risk forecasting and regime sensitivity (source: `paper.pdf`, pp. 9-11).

## 警告

- None.
"""


class NormalizeTests(unittest.TestCase):
    def _run_cases(self, *names: str) -> None:
        for name in names:
            with self.subTest(case=name.removeprefix("_case_")):
                getattr(self, name)()

    def test_valid_record_scenarios(self) -> None:
        self._run_cases("_case_parse_valid_record", "_case_validate_valid_record")

    def test_summary_scenarios(self) -> None:
        self._run_cases(
            "_case_six_question_summary_is_valid",
            "_case_six_question_summary_rejects_empty_block",
        )

    def test_schema_and_evidence_scenarios(self) -> None:
        self._run_cases(
            "_case_missing_required_section_fails",
            "_case_placeholder_warns",
            "_case_partial_terms_warn",
            "_case_keyword_without_evidence_fails",
            "_case_invalid_rag_term_weight_and_role_fail",
            "_case_required_summary_quality_sections_fail_when_missing",
            "_case_connection_hooks_need_evidence",
        )

    def test_limitation_and_signal_scenarios(self) -> None:
        self._run_cases(
            "_case_limitations_need_use_conditions",
            "_case_limitations_need_improvement_directions",
            "_case_limitation_bullets_need_structured_keys",
            "_case_limitation_bullets_need_evidence_or_rationale",
            "_case_signals_need_required_types",
            "_case_signals_need_evidence_or_rationale",
        )

    def _case_parse_valid_record(self) -> None:
        record = parse_normalized_record(VALID_RECORD)
        self.assertEqual(record.frontmatter["source"], "paper.pdf")
        self.assertEqual(record.title, "Example Paper")
        self.assertEqual(len(record.keywords), 8)
        self.assertEqual(record.rag_terms[0].term, "retail cash flows")
        self.assertEqual(record.rag_terms[0].aliases, ["retail order flow", "household flow"])
        self.assertEqual(record.axon_signals[0].type, "Strong Contribution")
        self.assertEqual(record.dendrite_signals[0].type, "Assumption")

    def _case_validate_valid_record(self) -> None:
        result = validate_normalized_record(VALID_RECORD)
        self.assertTrue(result.valid, result.errors)

    def _case_six_question_summary_is_valid(self) -> None:
        summary = """### 研究问题

The source asks a research question (source: `paper.pdf`, p. 1).

### 核心贡献

It contributes a source-backed result (source: `paper.pdf`, p. 2).

### 方法 / 数据 / 场景

It uses daily market data (source: `paper.pdf`, p. 3).

### 关键发现

It reports a measurable finding (source: `paper.pdf`, p. 4).

### 适用条件与局限

It is limited to one market (source: `paper.pdf`, p. 5).

### 可迁移价值

It supports a comparison workflow (source: `paper.pdf`, p. 6)."""
        legacy = VALID_RECORD.split("## 总结\n\n", 1)[1].split("\n\n## 文档在资料架中的作用", 1)[0]
        result = validate_normalized_record(VALID_RECORD.replace(legacy, summary, 1))
        self.assertTrue(result.valid, result.errors)

    def _case_six_question_summary_rejects_empty_block(self) -> None:
        summary = """### 研究问题

Question with evidence (source: `paper.pdf`, p. 1).

### 核心贡献

Contribution with evidence (source: `paper.pdf`, p. 2).

### 方法 / 数据 / 场景

Method with evidence (source: `paper.pdf`, p. 3).

### 关键发现

### 适用条件与局限

Limits with evidence (source: `paper.pdf`, p. 5).

### 可迁移价值

Value with evidence (source: `paper.pdf`, p. 6)."""
        legacy = VALID_RECORD.split("## 总结\n\n", 1)[1].split("\n\n## 文档在资料架中的作用", 1)[0]
        result = validate_normalized_record(VALID_RECORD.replace(legacy, summary, 1))
        self.assertFalse(result.valid)
        self.assertTrue(any("summary question is empty" in error for error in result.errors))

    def _case_missing_required_section_fails(self) -> None:
        result = validate_normalized_record(VALID_RECORD.replace("## 局限性", "## Scope Limits"))
        self.assertFalse(result.valid)
        self.assertTrue(any("missing sections" in error for error in result.errors))

    def _case_placeholder_warns(self) -> None:
        result = validate_normalized_record(VALID_RECORD.replace("None.", "<None, extraction limitation, or uncertainty.>"))
        self.assertTrue(result.valid, result.errors)
        self.assertIn("placeholder text remains; it should be replaced with source-metadata unknowns", result.warnings)

    def _case_partial_terms_warn(self) -> None:
        keywords = "\n".join(VALID_RECORD.split("## 关键词\n\n", 1)[1].split("\n\n## RAG 术语", 1)[0].splitlines()[:7])
        text = VALID_RECORD.replace(
            VALID_RECORD.split("## 关键词\n\n", 1)[1].split("\n\n## RAG 术语", 1)[0],
            keywords,
            1,
        )
        rag = text.split("## RAG 术语\n\n", 1)[1].split("\n\n## 知识图谱标签", 1)[0]
        text = text.replace(rag, "", 1)

        result = validate_normalized_record(text)

        self.assertTrue(result.valid, result.errors)
        self.assertTrue(any("keywords contain 7" in warning for warning in result.warnings))
        self.assertTrue(any("RAG Terms section is empty" in warning for warning in result.warnings))

    def _case_keyword_without_evidence_fails(self) -> None:
        text = VALID_RECORD.replace(
            "`retail cash flows` — central investor-flow variable; evidence: p. 1 abstract",
            "`retail cash flows` — central investor-flow variable",
        )
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("keyword has no evidence" in error for error in result.errors))

    def _case_invalid_rag_term_weight_and_role_fail(self) -> None:
        text = VALID_RECORD.replace("weight: 5", "weight: 9", 1).replace("role: topic", "role: generic", 1)
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("weight must be 1-5" in error for error in result.errors))
        self.assertTrue(any("invalid rag term role" in error for error in result.errors))

    def _case_required_summary_quality_sections_fail_when_missing(self) -> None:
        result = validate_normalized_record(VALID_RECORD.replace("## 连接钩子", "## Related Notes"))
        self.assertFalse(result.valid)
        self.assertTrue(any("missing sections" in error for error in result.errors))

    def _case_connection_hooks_need_evidence(self) -> None:
        text = VALID_RECORD.replace(
            "## 连接钩子\n\n"
            "- `retail cash flows` (topic): connect to records about retail order flow and internalized trade imbalances (source: `paper.pdf`, p. 1).\n"
            "- `volatility prediction` (finding): connect to records about risk forecasting and regime sensitivity (source: `paper.pdf`, pp. 9-11).",
            "## 连接钩子\n\n"
            "- `retail cash flows` (topic): connect to records about retail order flow and internalized trade imbalances.",
        )
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("Connection Hooks has no explicit evidence" in error for error in result.errors))

    def _case_limitations_need_use_conditions(self) -> None:
        text = VALID_RECORD.replace("### 使用条件", "### Usage Notes")
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertIn("Limitations missing Use Conditions", result.errors)

    def _case_limitations_need_improvement_directions(self) -> None:
        text = VALID_RECORD.replace("### 改进方向", "### Future Work")
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertIn("Limitations missing Improvement Directions", result.errors)

    def _case_limitation_bullets_need_structured_keys(self) -> None:
        text = VALID_RECORD.replace("  implication: Use the finding as market-specific evidence rather than assuming cross-market generalization.\n", "")
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("Use Conditions bullet 1 missing implication" in error for error in result.errors))

    def _case_limitation_bullets_need_evidence_or_rationale(self) -> None:
        text = VALID_RECORD.replace("  evidence: p. 3 data", "  evidence: author note")
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("Use Conditions bullet 1 has no evidence or rationale" in error for error in result.errors))

    def _case_signals_need_required_types(self) -> None:
        text = VALID_RECORD.replace("- type: Strong Contribution", "- type: Weak Hint")
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("Axon Signals missing signal types" in error for error in result.errors))
        self.assertTrue(any("invalid type" in error for error in result.errors))

    def _case_signals_need_evidence_or_rationale(self) -> None:
        text = VALID_RECORD.replace(
            "  signal: Retail flow persistence is presented as a predictive signal for future volatility.\n"
            "  evidence: pp. 9-11 results",
            "  signal: Retail flow persistence is presented as a predictive signal for future volatility.\n"
            "  evidence: author note",
        )
        result = validate_normalized_record(text)
        self.assertFalse(result.valid)
        self.assertTrue(any("Axon Signals entry 1 has no evidence or rationale" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
