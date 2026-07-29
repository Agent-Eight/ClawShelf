#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

payload = json.load(sys.stdin)
expected = sys.argv[1]
if not any(expected in json.dumps(item) for item in payload):
    raise SystemExit(f"Expected {expected!r} in QMD search results")
