#!/usr/bin/env python3
"""Create the small binary source fixtures used by tests and smoke runs."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "examples" / "fixture-collection" / "sources"


def make_pdf() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 14 Tf 72 720 Td (River restoration evidence) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    with (SOURCES / "sample.pdf").open("wb") as handle:
        writer.write(handle)


def make_xlsx() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Budget"
    sheet.append(["Metric", "Value"])
    sheet.append(["Cost", 4])
    sheet.append(["Double", "=B2*2"])
    workbook.save(SOURCES / "sample.xlsx")


def main() -> None:
    SOURCES.mkdir(parents=True, exist_ok=True)
    make_pdf()
    make_xlsx()


if __name__ == "__main__":
    main()
