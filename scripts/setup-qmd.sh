#!/usr/bin/env bash
set -euo pipefail
QMD_VERSION=2.5.3
command -v node >/dev/null || { echo 'Node.js 22+ is required for QMD.' >&2; exit 1; }
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)' || { echo 'Node.js 22+ is required for QMD.' >&2; exit 1; }
command -v npm >/dev/null
if [[ $(uname -s) == Darwin ]]; then
  command -v brew >/dev/null && brew list sqlite >/dev/null 2>&1 || {
    echo "macOS QMD requires Homebrew SQLite. Run 'brew install sqlite'." >&2; exit 1;
  }
fi
prefix="${CLAWSHELF_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/clawshelf}/qmd"
qmd="$prefix/bin/qmd"
version=''
if [[ -x "$qmd" ]]; then version=$("$qmd" --version 2>/dev/null || true); fi
if [[ "$version" != "qmd $QMD_VERSION" && "$version" != "qmd $QMD_VERSION ("* && "$version" != "$QMD_VERSION" ]]; then
  npm install --global --prefix "$prefix" "@tobilu/qmd@$QMD_VERSION"
fi
[[ -x "$qmd" ]] || { echo "QMD binary not found: $qmd" >&2; exit 1; }
"$qmd" --version
