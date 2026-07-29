#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export QMD_CONFIG_DIR="$TMP/config"
export XDG_CACHE_HOME="$TMP/cache"
QMD_BIN="${QMD_BIN:-$(npm prefix -g)/bin/qmd}"

uv run --locked python "$ROOT/scripts/create-fixtures.py"
if "$QMD_BIN" collection show clawshelf-fixture >/dev/null 2>&1; then
  "$QMD_BIN" update
else
  "$QMD_BIN" collection add "$ROOT/examples/fixture-collection/clawshelf/normalized" --name clawshelf-fixture --mask "**/*.md"
fi
"$QMD_BIN" search "river restoration" -c clawshelf-fixture --format json | \
  uv run --locked python "$ROOT/scripts/assert-fixture-search.py" river-restoration.md
uv run --locked python -m unittest discover -s "$ROOT/tests"
