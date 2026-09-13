#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# The pointer preserves an install-time XDG location in background processes.
data="${CLAWSHELF_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/clawshelf}"
if [[ -z ${CLAWSHELF_DATA_DIR:-} && -f "$ROOT/.clawshelf-runtime" ]]; then
  IFS= read -r data < "$ROOT/.clawshelf-runtime"
fi
if [[ -f "$data/tools.paths" ]]; then
  { IFS= read -r uv; IFS= read -r node; IFS= read -r qmd; IFS= read -r host; } < "$data/tools.paths"
  export PATH="$(dirname "$uv"):$(dirname "$node"):$(dirname "$qmd"):$(dirname "$host"):${PATH:-/usr/bin:/bin}"
  export QMD_BIN="${QMD_BIN:-$qmd}"
else
  uv="${UV_BIN:-uv}"
fi
case "${1:-}" in
  python) shift; exec "$uv" run --locked --project "$ROOT" python "$@" ;;
  qmd) shift; exec "${QMD_BIN:-qmd}" "$@" ;;
  *) echo 'Usage: run.sh python <script/arguments> | qmd <arguments>' >&2; exit 2 ;;
esac
