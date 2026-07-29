#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it with 'brew install uv' or https://docs.astral.sh/uv/getting-started/installation/." >&2
  exit 1
fi

uv sync --locked
"$ROOT/scripts/setup-qmd.sh"
