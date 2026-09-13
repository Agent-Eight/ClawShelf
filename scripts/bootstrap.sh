#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export CLAWSHELF_DATA_DIR="${CLAWSHELF_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/clawshelf}"
mkdir -p "$CLAWSHELF_DATA_DIR"
CLAWSHELF_DATA_DIR=$(cd "$CLAWSHELF_DATA_DIR" && pwd -P)
uv=${UV_BIN:-$(command -v uv || true)}
[[ -n "$uv" ]] || { echo 'uv is required. Run the one-step installer.' >&2; exit 1; }
uv=$(command -v "$uv")
node=$(command -v node)
# Local development remains usable without an OpenClaw installation.
host=$(command -v openclaw || command -v node)
"$uv" sync --locked --project "$ROOT" --python 3.11
bash "$ROOT/scripts/setup-qmd.sh"
qmd="$CLAWSHELF_DATA_DIR/qmd/bin/qmd"
# Plain path records, never executable shell configuration.
for value in "$uv" "$node" "$qmd" "$host" "$CLAWSHELF_DATA_DIR"; do
  [[ "$value" == /* && "$value" != *$'\n'* ]] || { echo 'Tool paths must be absolute and contain no newline.' >&2; exit 1; }
done
printf '%s\n' "$uv" "$node" "$qmd" "$host" > "$CLAWSHELF_DATA_DIR/tools.paths"
printf '%s\n' "$CLAWSHELF_DATA_DIR" > "$ROOT/.clawshelf-runtime"
