from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.auto_normalize import (
    NORMALIZER_REVISION,
    SECTION_INPUT_BUDGET,
    _parse_markdown_sections,
    _select_sections,
    normalize_sources,
)
from clawshelf.keyword_worker import (
    KeywordExtraction,
    KeywordSignal,
    LimitationImprovement,
    LimitationUseCondition,
    RagSignal,
    StructuredSignal,
    KeywordValidationError,
    KeywordWorkerError,
)
from clawshelf.models import ExtractionResult, source_record
from clawshelf.normalize import validate_normalized_record


def fake_keyword_worker(packet, model):
    return KeywordExtraction(
        title="Deep Reinforcement Learning for Algorithmic Trading",
        summary=(
            "The paper studies deep reinforcement learning for algorithmic trading policy search "
            "(source: `paper.md`, section: source text). It compares trading performance, risk control, "
            "and transaction cost constraints as source-backed evaluation concerns (source: `paper.md`, section: source text)."
        ),
        paper_role="Map role: method / evidence for trading policy design (source: `paper.md`, section: source text).",
        research_question="The source asks how deep reinforcement learning can support algorithmic trading policy search (source: `paper.md`, section: source text).",
        method_data_setting="Deep reinforcement learning, trading policy search, stock market data, and transaction cost constraints (source: `paper.md`, section: source text).",
        topics=["Deep reinforcement learning", "Algorithmic trading"],
        keywords=[
            KeywordSignal("deep reinforcement learning", "central method", "section: source text"),
            KeywordSignal("algorithmic trading", "central task", "section: source text"),
            KeywordSignal("trading policy search", "optimization target", "section: source text"),
            KeywordSignal("stock market data", "data setting", "section: source text"),
            KeywordSignal("transaction cost constraints", "practical constraint", "section: source text"),
            KeywordSignal("risk control", "evaluation concern", "section: source text"),
            KeywordSignal("trading performance", "main outcome", "section: source text"),
            KeywordSignal("backtesting evidence", "evidence mode", "section: source text"),
        ],
        rag_terms=[
            RagSignal("deep reinforcement learning", 5, ["RL"], "section: source text", "method"),
            RagSignal("algorithmic trading", 5, [], "section: source text", "topic"),
            RagSignal("transaction cost constraints", 4, [], "section: source text", "limitation"),
        ],
        key_claims=[
            "Deep reinforcement learning is used for trading policy search (source: `paper.md`, section: source text)."
        ],
        methods_or_basis="The method basis is deep reinforcement learning over stock market data (source: `paper.md`, section: source text).",
        use_conditions=[
            LimitationUseCondition(
                "Evaluation Limits",
                "The record only states that careful review is needed before synthesis.",
                "Use it as intake evidence until evaluation details are reviewed.",
                "section: source text",
            )
        ],
        improvement_directions=[
            LimitationImprovement(
                "Evaluation Limits",
                "Extract full benchmark design, baselines, and transaction-cost assumptions.",
                "This would make the record safer for idea generation and synthesis.",
                "rationale: source text says careful review is needed before synthesis",
            )
        ],
        axon_signals=[
            StructuredSignal("Strong Contribution", "DRL is framed as a method for trading policy search.", "section: source text"),
            StructuredSignal("Strong Method", "Trading policy search is performed with deep reinforcement learning.", "section: source text"),
            StructuredSignal("Strong Limitation", "The source requires careful review before synthesis.", "section: source text"),
            StructuredSignal("Strong Application Method", "Use DRL policy search as an application method for trading tasks.", "section: source text"),
        ],
        dendrite_signals=[
            StructuredSignal("Assumption", "Trading data is sufficient for policy search.", "rationale: inferred from section: source text"),
            StructuredSignal("Data / Domain Boundary", "The setting is stock market data.", "section: source text"),
            StructuredSignal("Metric Choice", "Trading performance and risk control shape evaluation.", "section: source text"),
            StructuredSignal("Failure Mode", "Transaction costs may weaken policy performance.", "section: source text"),
            StructuredSignal("Extension Hint", "Compare with records about transaction-cost-aware evaluation.", "section: source text"),
        ],
        idea_signals=[
            "Speculative: connect DRL trading policy search with records whose limitations mention transaction costs (source: `paper.md`, section: source text)."
        ],
        connection_hooks=[
            "`transaction cost constraints` can connect to execution-cost and backtesting records (source: `paper.md`, section: source text)."
        ],
        evidence_notes=["LLM worker used extracted source text as packet evidence (source: `paper.md`, section: source text)."],
        warnings=[],
        model=model,
    )


def six_question_keyword_worker(packet, model):
    result = fake_keyword_worker(packet, model)
    evidence = "(source: `paper.md`, section: source text)."
    summary = "\n\n".join(
        [
            f"### 研究问题\n\nThe source studies algorithmic trading policy search {evidence}",
            f"### 核心贡献\n\nIt frames deep reinforcement learning as the core contribution {evidence}",
            f"### 方法 / 数据 / 场景\n\nIt uses stock-market data and reinforcement learning {evidence}",
            f"### 关键发现\n\nIt reports backtesting evidence and risk-control concerns {evidence}",
            f"### 适用条件与局限\n\nTransaction costs limit downstream use {evidence}",
            f"### 可迁移价值\n\nThe method can inform trading-policy comparisons {evidence}",
        ]
    )
    return replace(result, summary=summary)


class AutoNormalizeTests(unittest.TestCase):
    def test_normalizes_source_into_valid_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.md"
            source.write_text(
                "# Deep Reinforcement Learning for Algorithmic Trading\n\n"
                "Deep reinforcement learning is used for algorithmic trading policy search in stock market data. "
                "The method compares trading performance, risk control, and transaction cost constraints. "
                "The paper reports backtesting evidence but needs careful review before synthesis.",
                encoding="utf-8",
            )

            results = normalize_sources(root, [source], keyword_worker=fake_keyword_worker)

            self.assertEqual(results[0].status, "normalized")
            self.assertIsNotNone(results[0].record_path)
            record_text = results[0].record_path.read_text(encoding="utf-8")
            validation = validate_normalized_record(record_text)
            self.assertTrue(validation.valid, validation.errors)
            self.assertIn("source: paper.md", record_text)
            self.assertIn("deep reinforcement learning", record_text.lower())

    def test_rendered_record_replaces_direct_worker_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.md"
            source.write_text("# Paper\n\n## Introduction\n\nSource-backed evidence.", encoding="utf-8")

            result = normalize_sources(
                root,
                [source],
                keyword_worker=lambda packet, model: replace(
                    fake_keyword_worker(packet, model),
                    paper_role="<unknown> (source: `paper.md`, section: Introduction).",
                ),
            )[0]

            self.assertEqual(result.status, "normalized")
            record_text = result.record_path.read_text(encoding="utf-8")
            self.assertNotIn("<unknown>", record_text)
            self.assertIn("unknown (source: extraction metadata)", record_text)
            self.assertIn("Replaced 1 angle-bracket placeholder", record_text)
            self.assertIn("transaction cost constraints", record_text)
            self.assertNotIn("source-backed extraction", record_text)
            self.assertIn("## 总结", record_text)
            self.assertIn("## 局限性", record_text)
            self.assertIn("### 使用条件", record_text)
            self.assertIn("### 改进方向", record_text)
            self.assertTrue((root / "clawshelf" / "clawshelf-metadata.md").exists())

    def test_six_question_record_is_reused_without_second_worker_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.md"
            source.write_text("# Paper\n\nSource text with enough evidence for normalization.", encoding="utf-8")
            calls = []

            def worker(packet, model):
                calls.append(packet)
                return six_question_keyword_worker(packet, model)

            first = normalize_sources(root, [source], keyword_worker=worker)
            second = normalize_sources(root, [source], keyword_worker=worker)

            self.assertEqual(first[0].status, "normalized")
            self.assertEqual(second[0].status, "current")
            self.assertEqual(len(calls), 1)

    def test_same_stem_sources_get_distinct_record_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a" / "report.md"
            second = root / "b" / "report.md"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("first source", encoding="utf-8")
            second.write_text("second source", encoding="utf-8")

            results = normalize_sources(root, [first, second], keyword_worker=fake_keyword_worker)

            self.assertEqual([result.status for result in results], ["normalized", "normalized"])
            self.assertNotEqual(results[0].record_path, results[1].record_path)

    def test_markdown_sections_group_nested_headings_under_main_body_sections(self) -> None:
        sections = _parse_markdown_sections(
            "# Paper Title\n\n"
            "Title context.\n\n"
            "## Methodology\n\n"
            "Method overview.\n\n"
            "### Data\n\n"
            "Dataset details.\n\n"
            "```markdown\n"
            "## Not a real heading\n"
            "```\n"
        )

        self.assertEqual([section.heading for section in sections], ["Methodology"])
        self.assertEqual(sections[0].heading_path, ("Methodology",))
        self.assertIn("### Data", sections[0].text)
        self.assertIn("## Not a real heading", sections[0].text)

    def test_markdown_sections_promote_leading_deep_abstract(self) -> None:
        sections = _parse_markdown_sections(
            "# Paper Title\n\n"
            "### Author Names\n\n"
            "##### Abstract\n\n"
            "Abstract evidence.\n\n"
            "## 1 Introduction\n\n"
            "Introduction evidence.\n\n"
            "### Contribution\n\n"
            "Nested contribution evidence."
        )

        self.assertEqual([section.heading for section in sections], ["Abstract", "1 Introduction"])
        self.assertEqual(sections[0].role, "abstract")
        self.assertNotIn("Author Names", sections[0].text)
        self.assertIn("### Contribution", sections[1].text)

    def test_heading_free_source_becomes_one_document_section(self) -> None:
        selection = _select_sections("Plain source text without a Markdown heading.")

        self.assertEqual(len(selection.sections), 1)
        self.assertEqual(selection.sections[0].heading_path, "Document")
        self.assertIn("No usable Markdown heading hierarchy", selection.warnings[0])

    def test_unstructured_source_truncates_at_budget(self) -> None:
        selection = _select_sections("paragraph one\n\n" + ("word " * 100), budget=80)

        self.assertLessEqual(len(selection.sections[0].text), 80)
        self.assertTrue(selection.sections[0].text.endswith("[truncated]"))
        self.assertTrue(any("truncated" in warning for warning in selection.warnings))

    def test_section_selection_reports_only_eligible_level_one_sections(self) -> None:
        content = "\n\n".join(
            [
                "# Paper",
                "Title context.",
                "## Abstract",
                "abstract " * 30,
                "## Introduction",
                "introduction " * 30,
                "## Methods",
                "methods " * 30,
                "## Results",
                "results " * 30,
                "## References",
                "references " * 100,
                "## Appendix A",
                "appendix " * 100,
            ]
        )

        selection = _select_sections(content, budget=1_500)
        paths = {section.heading_path for section in selection.sections}

        self.assertTrue({"Abstract", "Introduction", "Methods", "Results"} <= paths)
        self.assertNotIn("References", paths)
        self.assertNotIn("Appendix A", paths)
        self.assertEqual(
            selection.warnings,
            [
                "Section input exceeded the 1500-character budget; selected 4 of 4 eligible "
                "Level-1 sections and omitted 0. Excluded 2 reference/appendix sections."
            ],
        )

    def test_long_source_uses_one_worker_call_and_records_partial_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.md"
            source.write_text(
                "# Paper\n\n"
                + "\n\n".join(
                    f"## Section {index}\n\n" + ("evidence " * 1_000)
                    for index in range(8)
                ),
                encoding="utf-8",
            )
            packets = []

            def worker(packet, model):
                packets.append(packet)
                return fake_keyword_worker(packet, model)

            result = normalize_sources(root, [source], keyword_worker=worker)[0]

            self.assertEqual(result.status, "normalized")
            self.assertEqual(len(packets), 1)
            self.assertLessEqual(
                sum(len(section.text) for section in packets[0].section_packets),
                SECTION_INPUT_BUDGET,
            )
            record = result.record_path.read_text(encoding="utf-8")
            self.assertIn("Section input exceeded", record)
            self.assertEqual(result.coverage, "partial")
            self.assertIn("coverage: partial", record)

    def test_pdf_cache_skips_conversion_and_old_method_is_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.pdf"
            source.write_bytes(b"stable pdf bytes")
            extraction = ExtractionResult(
                source_record(source),
                "pymupdf4llm-markdown",
                "# Paper\n\n## Abstract\n\nSource-backed abstract evidence.",
            )
            packets = []

            def worker(packet, model):
                packets.append(packet)
                return fake_keyword_worker(packet, model)

            with patch("clawshelf.auto_normalize.ExtractorRegistry.extract", return_value=extraction) as extract:
                first = normalize_sources(root, [source], keyword_worker=worker)[0]
            self.assertEqual(first.status, "normalized")
            self.assertEqual(extract.call_count, 1)
            self.assertEqual(len(packets), 1)
            payload = packets[0].to_payload()["section_packets"]
            self.assertEqual(payload[0]["evidence_ref"], "section: Abstract")
            self.assertNotIn("page", payload[0]["evidence_ref"].lower())

            with patch("clawshelf.auto_normalize.ExtractorRegistry.extract") as extract:
                second = normalize_sources(root, [source], keyword_worker=fake_keyword_worker)[0]
            self.assertEqual(second.status, "current")
            extract.assert_not_called()

            record_text = first.record_path.read_text(encoding="utf-8")
            first.record_path.write_text(
                record_text.replace(
                    "extraction_method: pymupdf4llm-markdown",
                    "extraction_method: pdf",
                    1,
                ),
                encoding="utf-8",
            )
            with patch("clawshelf.auto_normalize.ExtractorRegistry.extract", return_value=extraction) as extract:
                third = normalize_sources(root, [source], keyword_worker=fake_keyword_worker)[0]
            self.assertEqual(third.status, "normalized")
            self.assertEqual(extract.call_count, 1)

            first.record_path.write_text(
                record_text.replace(
                    f"normalizer_revision: {NORMALIZER_REVISION}",
                    "normalizer_revision: legacy-page-packets",
                    1,
                ),
                encoding="utf-8",
            )
            with patch("clawshelf.auto_normalize.ExtractorRegistry.extract", return_value=extraction) as extract:
                fourth = normalize_sources(root, [source], keyword_worker=fake_keyword_worker)[0]
            self.assertEqual(fourth.status, "normalized")
            self.assertEqual(extract.call_count, 1)

    def test_invalid_output_is_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.md"
            source.write_text("source text", encoding="utf-8")

            result = normalize_sources(
                root,
                [source],
                keyword_worker=lambda packet, model: replace(fake_keyword_worker(packet, model), summary="One sentence."),
            )[0]

            self.assertEqual(result.status, "invalid")
            self.assertIsNone(result.record_path)
            self.assertEqual(list((root / "clawshelf" / "normalized").glob("*.md")), [])

    def test_worker_failure_does_not_stop_remaining_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / "a.md", root / "b.md"]
            for source in sources:
                source.write_text("source text", encoding="utf-8")

            def worker(packet, model):
                if packet.source == "a.md":
                    raise KeywordWorkerError("host timeout")
                return fake_keyword_worker(packet, model)

            results = normalize_sources(root, sources, keyword_worker=worker)

            self.assertEqual([result.status for result in results], ["llm_unavailable", "normalized"])

    def test_validation_failure_is_not_reported_as_llm_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.md"
            source.write_text("source text", encoding="utf-8")

            result = normalize_sources(
                root,
                [source],
                keyword_worker=lambda packet, model: (_ for _ in ()).throw(
                    KeywordValidationError(
                        "paper_role.evidence must include source evidence"
                    )
                ),
            )[0]

            self.assertEqual(result.status, "validation_failed")
            self.assertIn("paper_role.evidence", result.warnings[0])

    def test_failed_job_reuses_checkpointed_pdf_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.pdf"
            source.write_bytes(b"stable pdf bytes")
            extraction = ExtractionResult(
                source_record(source), "pymupdf4llm-markdown", "# Paper\n\n## Abstract\n\nSource-backed abstract evidence."
            )
            with patch("clawshelf.auto_normalize.ExtractorRegistry.extract", return_value=extraction) as extract:
                first = normalize_sources(
                    root, [source], keyword_worker=lambda packet, model: (_ for _ in ()).throw(KeywordWorkerError("bad JSON"))
                )[0]
            self.assertEqual(first.status, "llm_unavailable")
            self.assertEqual(extract.call_count, 1)

            with patch("clawshelf.auto_normalize.ExtractorRegistry.extract") as extract:
                second = normalize_sources(root, [source], keyword_worker=fake_keyword_worker)[0]
            self.assertEqual(second.status, "normalized")
            extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
