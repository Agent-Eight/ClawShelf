#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from clawshelf.extractors import ExtractorRegistry
from clawshelf.models import ProcessingWarning, is_url, source_record


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract-source.py <source-path-or-url>", file=sys.stderr)
        return 2
    arg = sys.argv[1]
    if is_url(arg):
        result = ExtractorRegistry().extract(arg)
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 0 if result.content else 1
    path = Path(arg)
    if not path.is_file():
        print(json.dumps({"warnings": [{"code": "missing_source", "message": str(path)}]}))
        return 1
    result = ExtractorRegistry().extract(path)
    if result is None:
        result = {
            "source": source_record(path).__dict__,
            "extraction_method": "unsupported",
            "content": "",
            "warnings": [ProcessingWarning("unsupported_type", f"No deterministic extractor for {path.suffix}").__dict__],
        }
    else:
        result = result.to_dict()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
