from __future__ import annotations

from contextlib import redirect_stderr
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pymupdf
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.extractors import ExtractorRegistry, UrlExtractor, XlsxExtractor
from clawshelf.models import is_url, source_record


def _fake_response(body: bytes, content_type: str = "text/html", charset: str = "utf-8"):
    response = MagicMock()
    response.read.return_value = body
    response.headers.get_content_type.return_value = content_type
    response.headers.get_content_charset.return_value = charset
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class ExtractorTests(unittest.TestCase):
    def _run_cases(self, *names: str) -> None:
        for name in names:
            with self.subTest(case=name.removeprefix("_case_")):
                getattr(self, name)()

    def test_local_source_scenarios(self) -> None:
        self._run_cases(
            "_case_text_and_unsupported_source",
            "_case_source_fingerprint_changes_with_content",
            "_case_xlsx_preserves_values_and_formulas",
            "_case_pdf_extracts_fixture_text",
            "_case_pdf_preserves_markdown_headings",
            "_case_pdf_preserves_columns_and_tables",
            "_case_pdf_retries_empty_image_text_with_forced_ocr",
        )

    def test_url_scenarios(self) -> None:
        self._run_cases(
            "_case_is_url_distinguishes_urls_from_paths",
            "_case_registry_routes_urls_to_url_extractor",
            "_case_url_extractor_converts_html_to_markdown",
            "_case_url_extractor_plain_text_passthrough",
        )

    def test_extraction_failure_scenarios(self) -> None:
        self._run_cases(
            "_case_url_extractor_fetch_failure_is_a_warning",
            "_case_pdf_empty_text_is_a_warning",
            "_case_corrupt_pdf_is_a_warning",
            "_case_latin1_text_uses_replacement_characters",
        )

    def _case_text_and_unsupported_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "note.txt"
            text.write_text("river evidence", encoding="utf-8")
            result = ExtractorRegistry().extract(text)
            self.assertEqual(result.content, "river evidence")
            unsupported = root / "unknown.dat"
            unsupported.write_text("requires fallback", encoding="utf-8")
            self.assertIsNone(ExtractorRegistry().extract(unsupported))

    def _case_source_fingerprint_changes_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text("first", encoding="utf-8")
            first = source_record(path).sha256
            self.assertEqual(first, source_record(path).sha256)
            path.write_text("second", encoding="utf-8")
            self.assertNotEqual(first, source_record(path).sha256)

    def _case_xlsx_preserves_values_and_formulas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Budget"
            sheet.append(["Cost", 4])
            sheet.append(["Double", "=B2*2"])
            workbook.save(path)

            content = XlsxExtractor().extract(path).content

            self.assertIn("## Sheet: Budget", content)
            self.assertIn("| Cost | 4 |", content)
            self.assertIn("=B2*2", content)

    def _case_pdf_extracts_fixture_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((72, 72), "River restoration evidence")
            document.save(path)
            document.close()

            result = ExtractorRegistry().extract(path)

            self.assertIn("River restoration evidence", result.content)
            self.assertEqual(result.extraction_method, "pymupdf4llm-markdown")

    def _case_pdf_preserves_markdown_headings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "structured.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((72, 72), "Structured Research Paper", fontsize=24)
            page.insert_text((72, 120), "Introduction", fontsize=18)
            page.insert_text((72, 145), "The introduction explains the research problem.", fontsize=11)
            page.insert_text((72, 200), "Methodology", fontsize=18)
            page.insert_text((72, 230), "Data", fontsize=14)
            page.insert_text((72, 255), "The study uses structured market data.", fontsize=11)
            document.save(path)
            document.close()

            content = ExtractorRegistry().extract(path).content

            self.assertIn("# Structured Research Paper", content)
            self.assertIn("## Introduction", content)
            self.assertIn("## Methodology", content)
            self.assertIn("### Data", content)

    def _case_pdf_preserves_columns_and_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_textbox(
                pymupdf.Rect(72, 72, 280, 160),
                "Left column evidence describes the research question.",
                fontsize=11,
            )
            page.insert_textbox(
                pymupdf.Rect(320, 72, 528, 160),
                "Right column evidence describes the main result.",
                fontsize=11,
            )
            x_positions = [72, 220, 368]
            y_positions = [220, 250, 280]
            for x in x_positions:
                page.draw_line((x, y_positions[0]), (x, y_positions[-1]))
            for y in y_positions:
                page.draw_line((x_positions[0], y), (x_positions[-1], y))
            page.insert_text((82, 241), "Metric", fontsize=10)
            page.insert_text((230, 241), "Value", fontsize=10)
            page.insert_text((82, 271), "Accuracy", fontsize=10)
            page.insert_text((230, 271), "92%", fontsize=10)
            document.save(path)
            document.close()

            content = ExtractorRegistry().extract(path).content

            self.assertIn("Left column evidence", content)
            self.assertIn("Right column evidence", content)
            self.assertIn("|Metric|Value|", content.replace(" ", ""))
            self.assertIn("|Accuracy|92%|", content.replace(" ", ""))

    def _case_pdf_retries_empty_image_text_with_forced_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ocr.pdf"
            document = pymupdf.open()
            document.new_page(width=400, height=160)
            document.save(path)
            document.close()

            with patch(
                "clawshelf.extractors.PdfExtractor._to_markdown",
                side_effect=["", "# OCR Structure Evidence"],
            ) as convert:
                result = ExtractorRegistry().extract(path)

            self.assertEqual(result.content, "# OCR Structure Evidence")
            self.assertEqual(convert.call_count, 2)
            self.assertFalse(convert.call_args_list[0].kwargs["force_ocr"])
            self.assertTrue(convert.call_args_list[1].kwargs["force_ocr"])

    def _case_is_url_distinguishes_urls_from_paths(self) -> None:
        self.assertTrue(is_url("https://example.com/report"))
        self.assertTrue(is_url("http://example.com"))
        self.assertFalse(is_url("/local/path/report.pdf"))
        self.assertFalse(is_url("report.pdf"))

    def _case_registry_routes_urls_to_url_extractor(self) -> None:
        with patch("clawshelf.extractors.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _fake_response(b"<html><body><p>River restoration evidence</p></body></html>")
            result = ExtractorRegistry().extract("https://example.com/river-notes")
            self.assertEqual(result.extraction_method, "url")
            self.assertIn("River restoration evidence", result.content)
            self.assertEqual(result.source.source_type, "url")

    def _case_url_extractor_converts_html_to_markdown(self) -> None:
        html = b"<html><body><h1>Title</h1><p>Some <strong>bold</strong> text.</p></body></html>"
        with patch("clawshelf.extractors.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _fake_response(html)
            result = UrlExtractor().extract("https://example.com/article")
            self.assertIn("# Title", result.content)
            self.assertIn("**bold**", result.content)
            self.assertEqual(result.warnings, [])

    def _case_url_extractor_plain_text_passthrough(self) -> None:
        with patch("clawshelf.extractors.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _fake_response(b"raw text content", content_type="text/plain")
            result = UrlExtractor().extract("https://example.com/notes.txt")
            self.assertEqual(result.content, "raw text content")

    def _case_url_extractor_fetch_failure_is_a_warning(self) -> None:
        with patch("clawshelf.extractors.urlopen", side_effect=URLError("no route to host")):
            result = UrlExtractor().extract("https://unreachable.example.com")
            self.assertEqual(result.content, "")
            self.assertEqual(result.warnings[0].code, "fetch_failed")

    def _case_pdf_empty_text_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pdf"
            document = pymupdf.open()
            document.new_page(width=72, height=72)
            document.save(path)
            document.close()
            result = ExtractorRegistry().extract(path)
            self.assertEqual(result.extraction_method, "pymupdf4llm-markdown")
            self.assertEqual(result.warnings[0].code, "empty_pdf")

    def _case_corrupt_pdf_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.pdf"
            path.write_bytes(b"not a pdf")
            with redirect_stderr(io.StringIO()):
                result = ExtractorRegistry().extract(path)
            self.assertEqual(result.content, "")
            self.assertEqual(result.warnings[0].code, "pdf_read_failed")

    def _case_latin1_text_uses_replacement_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.txt"
            path.write_bytes(b"caf\xe9 evidence")
            result = ExtractorRegistry().extract(path)
            self.assertIn("caf", result.content)
            self.assertIn("\ufffd", result.content)
