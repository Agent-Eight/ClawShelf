#!/usr/bin/env sh
set -eu

QMD_VERSION="${QMD_VERSION:-2.5.3}"

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js 22+ is required for QMD." >&2
  exit 1
fi
if [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
  echo "Node.js 22+ is required for QMD." >&2
  exit 1
fi
if [ "$(uname)" = "Darwin" ] && ! command -v brew >/dev/null 2>&1; then
  echo "macOS QMD requires Homebrew SQLite: install Homebrew, then run 'brew install sqlite'." >&2
  exit 1
fi
if [ "$(uname)" = "Darwin" ] && ! brew list sqlite >/dev/null 2>&1; then
  echo "macOS QMD requires SQLite. Run 'brew install sqlite' and retry." >&2
  exit 1
fi

npm install -g "@tobilu/qmd@${QMD_VERSION}"
QMD_BIN="${QMD_BIN:-$(npm prefix -g)/bin/qmd}"
if [ ! -x "$QMD_BIN" ]; then
  echo "QMD was installed but its npm global binary was not found: $QMD_BIN" >&2
  exit 1
fi
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/qmd" "${XDG_CACHE_HOME:-$HOME/.cache}/qmd"
"$QMD_BIN" --version
"$QMD_BIN" status
