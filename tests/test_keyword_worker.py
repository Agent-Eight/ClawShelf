from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.keyword_worker import (
    KeywordExtractionPacket,
    KeywordQualityError,
    KeywordValidationError,
    KeywordWorkerError,
    SectionEvidence,
    _run_openclaw_agent,
    openclaw_model_override,
    parse_keyword_extraction,
    run_openclaw_keyword_worker,
)
from unittest.mock import patch


def _response(**overrides) -> str:
    payload = {
        "title": "Retail Flow Persistence",
        "summary": "The source studies retail cash flows as a market signal (source: `paper.pdf`, p. 1). It uses persistence measures to evaluate volatility prediction (source: `paper.pdf`, pp. 3-9).",
        "paper_role": {
            "value": "evidence / idea seed for retail-flow signals",
            "evidence": "source: `paper.pdf`, p. 1",
        },
        "research_question": "The source asks whether retail cash flows predict volatility (source: `paper.pdf`, p. 1).",
        "method_data_setting": "Retail flow data and persistence measures in an equity-market setting (source: `paper.pdf`, pp. 3-9).",
        "topics": ["Retail cash flows", "Volatility prediction"],
        "keywords": [
            {"term": "retail cash flows", "why": "central variable", "evidence": "p. 1 abstract"},
            {"term": "volatility prediction", "why": "main finding", "evidence": "pp. 8-9 results"},
            {"term": "investor heterogeneity", "why": "core framing", "evidence": "p. 1 introduction"},
            {"term": "Hurst exponent", "why": "persistence metric", "evidence": "pp. 3-4 methods"},
            {"term": "detrended fluctuation analysis", "why": "estimation method", "evidence": "pp. 3-4 methods"},
            {"term": "rolling windows", "why": "time-varying analysis", "evidence": "p. 6 results"},
            {"term": "net flows", "why": "comparison variable", "evidence": "pp. 7-8 results"},
            {"term": "market persistence", "why": "measured phenomenon", "evidence": "pp. 4-6 results"},
        ],
        "rag_terms": [
            {"term": "retail cash flows", "weight": 5, "aliases": ["retail order flow"], "evidence": "p. 1 abstract", "role": "topic"},
            {"term": "volatility prediction", "weight": 5, "aliases": [], "evidence": "pp. 8-9 results", "role": "finding"},
        ],
        "key_claims": ["Retail cash flows predict volatility (source: `paper.pdf`, pp. 8-9)."],
        "methods_or_basis": "The basis is persistence analysis over retail flow data (source: `paper.pdf`, pp. 3-9).",
        "use_conditions": [
            {
                "category": "Scope Boundaries",
                "limitation": "The evidence is tied to one market setting.",
                "implication": "Use the result as market-specific evidence.",
                "evidence": "p. 3 data",
            }
        ],
        "improvement_directions": [
            {
                "category": "Generalization Limits",
                "direction": "Replicate across additional market settings.",
                "expected_value": "This would test external validity.",
                "evidence_or_rationale": "rationale: p. 3 data describes a bounded setting",
            }
        ],
        "axon_signals": [
            {"type": "Strong Contribution", "signal": "Retail flows predict volatility.", "evidence": "pp. 8-9 results"},
            {"type": "Strong Method", "signal": "Persistence is estimated with Hurst exponents.", "evidence": "pp. 3-4 methods"},
            {"type": "Strong Limitation", "signal": "The setting is market-specific.", "evidence": "p. 3 data"},
            {"type": "Strong Application Method", "signal": "Use flow persistence as a screening signal.", "evidence": "pp. 8-9 results"},
        ],
        "dendrite_signals": [
            {"type": "Assumption", "signal": "Investor groups are separable.", "evidence": "p. 1 introduction"},
            {"type": "Data / Domain Boundary", "signal": "The data is market-specific.", "evidence": "p. 3 data"},
            {"type": "Metric Choice", "signal": "Hurst exponents are the persistence metric.", "evidence": "pp. 3-4 methods"},
            {"type": "Failure Mode", "signal": "Transfer may fail across markets.", "evidence": "rationale: p. 3 data is bounded"},
            {"type": "Extension Hint", "signal": "Replicate across markets.", "evidence": "rationale: p. 3 data is bounded"},
        ],
        "idea_signals": ["Speculative: compare with market-microstructure records (source: `paper.pdf`, pp. 8-9)."],
        "connection_hooks": ["`retail cash flows` connects to order-flow records (source: `paper.pdf`, p. 1)."],
        "evidence_notes": ["Original source: `paper.pdf`."],
        "warnings": [],
        "model": "host-default",
    }
    payload.update(overrides)
    return json.dumps(payload)


class KeywordWorkerTests(unittest.TestCase):
    def _run_cases(self, *names: str) -> None:
        for name in names:
            with self.subTest(case=name.removeprefix("_case_")):
                getattr(self, name)()

    def test_parsing_scenarios(self) -> None:
        self._run_cases(
            "_case_accepts_single_string_for_string_list_fields",
            "_case_accepts_object_items_for_string_list_fields",
            "_case_accepts_object_items_for_warnings",
            "_case_methods_or_basis_falls_back_to_method_data_setting",
            "_case_accepts_common_limitation_field_aliases",
            "_case_parse_valid_keyword_worker_response",
            "_case_section_packet_serializes_section_only_evidence",
        )

    def test_tolerant_quality_cleanup_scenarios(self) -> None:
        self._run_cases(
            "_case_skips_boilerplate_keyword",
            "_case_skips_keyword_without_evidence",
            "_case_replaces_narrative_placeholder",
            "_case_allows_empty_rag_terms_after_filtering",
        )

    def test_host_runtime_scenarios(self) -> None:
        self._run_cases(
            "_case_host_model_selector_is_not_passed_as_openclaw_override",
            "_case_openclaw_timeout_is_converted_to_worker_error",
            "_case_validation_retry_repairs_previous_output_without_source_packet",
            "_case_partial_repair_patch_preserves_complete_candidate",
            "_case_exhausted_repairs_report_first_and_last_errors",
            "_case_restart_repairs_checkpointed_json_without_source_packet",
            "_case_contract_fingerprint_invalidates_exhausted_checkpoint",
        )

    def _case_host_model_selector_is_not_passed_as_openclaw_override(self) -> None:
        self.assertEqual(openclaw_model_override(""), "")
        self.assertEqual(openclaw_model_override("host:default"), "")
        self.assertEqual(openclaw_model_override("openai/gpt-4.1-mini"), "openai/gpt-4.1-mini")

    def _case_accepts_single_string_for_string_list_fields(self) -> None:
        result = parse_keyword_extraction(_response(key_claims="Retail cash flows predict volatility (source: `paper.pdf`, pp. 8-9)."))

        self.assertEqual(result.key_claims, ["Retail cash flows predict volatility (source: `paper.pdf`, pp. 8-9)."])

    def _case_accepts_object_items_for_string_list_fields(self) -> None:
        result = parse_keyword_extraction(
            _response(
                key_claims=[
                    {
                        "claim": "Retail cash flows predict volatility.",
                        "evidence": "source: `paper.pdf`, pp. 8-9",
                    }
                ]
            )
        )

        self.assertEqual(
            result.key_claims,
            ["Retail cash flows predict volatility. (evidence: source: `paper.pdf`, pp. 8-9)"],
        )

    def _case_accepts_object_items_for_warnings(self) -> None:
        result = parse_keyword_extraction(_response(warnings=[{"message": "Extraction was limited to visible text."}]))

        self.assertEqual(result.warnings, ["Extraction was limited to visible text."])

    def _case_methods_or_basis_falls_back_to_method_data_setting(self) -> None:
        payload = json.loads(_response())
        del payload["methods_or_basis"]

        result = parse_keyword_extraction(json.dumps(payload))

        self.assertEqual(result.methods_or_basis, payload["method_data_setting"])

    def _case_accepts_common_limitation_field_aliases(self) -> None:
        payload = json.loads(_response())
        payload["use_conditions"] = [
            {
                "category": "Scope Boundaries",
                "condition": "The evidence is tied to one market setting.",
                "source": "p. 3 data",
            }
        ]
        payload["improvement_directions"] = [
            {
                "category": "Generalization Limits",
                "improvement": "Replicate across additional market settings.",
                "rationale": "rationale: p. 3 data describes a bounded setting",
            }
        ]

        result = parse_keyword_extraction(json.dumps(payload))

        self.assertEqual(result.use_conditions[0].limitation, "The evidence is tied to one market setting.")
        self.assertEqual(result.use_conditions[0].implication, "The evidence is tied to one market setting.")
        self.assertEqual(result.improvement_directions[0].direction, "Replicate across additional market settings.")
        self.assertEqual(result.improvement_directions[0].expected_value, "Replicate across additional market settings.")

    def _case_parse_valid_keyword_worker_response(self) -> None:
        result = parse_keyword_extraction(_response(), model="")

        self.assertEqual(result.title, "Retail Flow Persistence")
        self.assertEqual(result.keywords[0].term, "retail cash flows")
        self.assertEqual(result.rag_terms[0].role, "topic")
        self.assertEqual(result.axon_signals[0].type, "Strong Contribution")
        self.assertIn("source: `paper.pdf`, p. 1", result.paper_role)

    def _case_partial_repair_patch_preserves_complete_candidate(self) -> None:
        invalid = json.loads(_response())
        invalid["paper_role"] = {"value": "method", "evidence": ""}
        outputs = [
            subprocess.CompletedProcess(["openclaw"], 0, json.dumps(invalid), ""),
            subprocess.CompletedProcess(
                ["openclaw"],
                0,
                json.dumps(
                    {
                        "paper_role": {
                            "value": "method",
                            "evidence": "section: Abstract",
                        }
                    }
                ),
                "",
            ),
        ]
        packet = KeywordExtractionPacket(
            source="source.pdf",
            title="Source title",
            content_warning="",
            section_packets=[
                SectionEvidence(
                    "Abstract",
                    "Abstract",
                    "abstract",
                    "source evidence",
                )
            ],
        )

        with patch(
            "clawshelf.keyword_worker.shutil.which",
            return_value="/usr/bin/openclaw",
        ), patch(
            "clawshelf.keyword_worker._run_openclaw_agent",
            side_effect=lambda *args: outputs.pop(0),
        ):
            result = run_openclaw_keyword_worker(packet, "host:default")

        self.assertEqual(len(result.keywords), 8)
        self.assertEqual(len(result.rag_terms), 2)
        self.assertIn("section: Abstract", result.paper_role)

    def _case_exhausted_repairs_report_first_and_last_errors(self) -> None:
        invalid = json.loads(_response())
        invalid["paper_role"] = {"value": "method", "evidence": ""}
        outputs = [
            subprocess.CompletedProcess(
                ["openclaw"],
                0,
                json.dumps(invalid if index == 0 else {"paper_role": {"evidence": ""}}),
                "",
            )
            for index in range(3)
        ]
        packet = KeywordExtractionPacket(
            source="source.pdf",
            title="Source title",
            content_warning="",
            section_packets=[
                SectionEvidence(
                    "Abstract",
                    "Abstract",
                    "abstract",
                    "source evidence",
                )
            ],
        )

        with patch(
            "clawshelf.keyword_worker.shutil.which",
            return_value="/usr/bin/openclaw",
        ), patch(
            "clawshelf.keyword_worker._run_openclaw_agent",
            side_effect=lambda *args: outputs.pop(0),
        ):
            with self.assertRaises(KeywordValidationError) as raised:
                run_openclaw_keyword_worker(packet, "host:default")

        self.assertIn("first_error=paper_role.evidence", str(raised.exception))
        self.assertIn("last_error=paper_role.evidence", str(raised.exception))

    def _case_section_packet_serializes_section_only_evidence(self) -> None:
        packet = KeywordExtractionPacket(
            source="paper.pdf",
            title="Paper",
            content_warning="",
            section_packets=[
                SectionEvidence(
                    heading="Data",
                    heading_path="Methodology > Data",
                    role="method / data / setting",
                    text="Dataset details.",
                )
            ],
        )

        payload = packet.to_payload()["section_packets"][0]

        self.assertEqual(payload["evidence_ref"], "section: Methodology > Data")
        self.assertNotIn("page", payload["evidence_ref"].lower())

    def _case_skips_boilerplate_keyword(self) -> None:
        payload = json.loads(_response())
        payload["keywords"][0]["term"] = "all-contract purchase arbitrage"

        result = parse_keyword_extraction(json.dumps(payload))

        self.assertEqual(len(result.keywords), 7)
        self.assertNotIn("all-contract purchase arbitrage", [item.term for item in result.keywords])
        self.assertTrue(any("Skipped keyword `all-contract purchase arbitrage`" in warning for warning in result.warnings))

    def _case_skips_keyword_without_evidence(self) -> None:
        payload = json.loads(_response())
        payload["keywords"][0]["evidence"] = "author note"

        result = parse_keyword_extraction(json.dumps(payload))

        self.assertEqual(len(result.keywords), 7)
        self.assertTrue(any("Skipped keyword `retail cash flows`" in warning for warning in result.warnings))

    def _case_replaces_narrative_placeholder(self) -> None:
        payload = json.loads(_response())
        payload["summary"] = "<unknown> (source: `paper.pdf`, p. 1)."

        result = parse_keyword_extraction(json.dumps(payload))

        self.assertNotIn("<unknown>", result.summary)
        self.assertIn("unknown (source: extraction metadata)", result.summary)
        self.assertTrue(any("Replaced angle-bracket placeholder in summary" in warning for warning in result.warnings))

    def _case_allows_empty_rag_terms_after_filtering(self) -> None:
        payload = json.loads(_response())
        payload["rag_terms"] = [
            {"term": "all-contract purchase arbitrage", "weight": 5, "aliases": [], "evidence": "p. 1 abstract", "role": "topic"}
        ]

        result = parse_keyword_extraction(json.dumps(payload))

        self.assertEqual(result.rag_terms, [])
        self.assertTrue(any("No valid RAG terms remained" in warning for warning in result.warnings))

    def _case_openclaw_timeout_is_converted_to_worker_error(self) -> None:
        with patch(
            "clawshelf.keyword_worker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["openclaw"], 1),
        ):
            with self.assertRaises(KeywordWorkerError):
                _run_openclaw_agent(["openclaw"], "prompt", 1)

    def _case_validation_retry_repairs_previous_output_without_source_packet(self) -> None:
        invalid = json.loads(_response())
        invalid["method_data_setting"] = ["invalid shape"]
        outputs = [
            subprocess.CompletedProcess(["openclaw"], 0, json.dumps(invalid), ""),
            subprocess.CompletedProcess(["openclaw"], 0, _response(), ""),
        ]
        prompts: list[str] = []

        def fake_run(command: list[str], prompt: str, timeout: int):
            prompts.append(prompt)
            return outputs.pop(0)

        packet = KeywordExtractionPacket(
            source="source.pdf",
            title="Source title",
            content_warning="",
            section_packets=[SectionEvidence("Abstract", "Abstract", "abstract", "source evidence")],
        )
        with patch("clawshelf.keyword_worker.shutil.which", return_value="/usr/bin/openclaw"), patch(
            "clawshelf.keyword_worker._run_openclaw_agent", side_effect=fake_run
        ):
            result = run_openclaw_keyword_worker(packet, "host:default")

        self.assertEqual(result.title, "Retail Flow Persistence")
        self.assertEqual(len(prompts), 2)
        self.assertIn("invalid shape", prompts[1])
        self.assertIn("method_data_setting must be a non-empty string", prompts[1])
        self.assertNotIn("source evidence", prompts[1])
        self.assertNotIn("source.pdf", prompts[1])

    def _case_restart_repairs_checkpointed_json_without_source_packet(self) -> None:
        invalid = json.loads(_response())
        invalid["method_data_setting"] = ["invalid shape"]
        packet = KeywordExtractionPacket(
            source="source.pdf",
            title="Source title",
            content_warning="",
            section_packets=[SectionEvidence("Abstract", "Abstract", "abstract", "source evidence")],
        )
        with tempfile.TemporaryDirectory() as directory:
            checkpoint_dir = Path(directory)
            first_outputs = [
                subprocess.CompletedProcess(["openclaw"], 0, json.dumps(invalid), ""),
                subprocess.CompletedProcess(["openclaw"], 1, "", "temporary worker failure"),
            ]
            with patch("clawshelf.keyword_worker.shutil.which", return_value="/usr/bin/openclaw"), patch(
                "clawshelf.keyword_worker._run_openclaw_agent", side_effect=lambda *args: first_outputs.pop(0)
            ):
                with self.assertRaises(KeywordWorkerError):
                    run_openclaw_keyword_worker(packet, "host:default", checkpoint_dir=checkpoint_dir)

            prompts: list[str] = []
            def repaired(command, prompt, timeout):
                prompts.append(prompt)
                return subprocess.CompletedProcess(["openclaw"], 0, _response(), "")

            with patch("clawshelf.keyword_worker.shutil.which", return_value="/usr/bin/openclaw"), patch(
                "clawshelf.keyword_worker._run_openclaw_agent", side_effect=repaired
            ):
                result = run_openclaw_keyword_worker(packet, "host:default", checkpoint_dir=checkpoint_dir)

        self.assertEqual(result.title, "Retail Flow Persistence")
        self.assertEqual(len(prompts), 1)
        self.assertIn("invalid shape", prompts[0])
        self.assertNotIn("source evidence", prompts[0])
        self.assertNotIn("source.pdf", prompts[0])

    def _case_contract_fingerprint_invalidates_exhausted_checkpoint(self) -> None:
        packet = KeywordExtractionPacket(
            source="source.pdf",
            title="Source title",
            content_warning="",
            section_packets=[
                SectionEvidence(
                    "Abstract",
                    "Abstract",
                    "abstract",
                    "source evidence",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            checkpoint_dir = Path(directory)
            (checkpoint_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "packet": packet.to_payload(),
                        "status": "failed",
                        "attempts": 3,
                        "validation_error": "rag_terms must be a list",
                        "raw_output": "raw-attempt-3.json",
                    }
                ),
                encoding="utf-8",
            )
            (checkpoint_dir / "raw-attempt-3.json").write_text(
                "{}",
                encoding="utf-8",
            )
            with patch(
                "clawshelf.keyword_worker.shutil.which",
                return_value="/usr/bin/openclaw",
            ), patch(
                "clawshelf.keyword_worker._run_openclaw_agent",
                return_value=subprocess.CompletedProcess(
                    ["openclaw"],
                    0,
                    _response(),
                    "",
                ),
            ) as run:
                result = run_openclaw_keyword_worker(
                    packet,
                    "host:default",
                    checkpoint_dir=checkpoint_dir,
                )

        self.assertEqual(result.title, "Retail Flow Persistence")
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
