#!/usr/bin/env bash
# This file is self-contained so it can also be piped to bash.
set -Eeuo pipefail
REPOSITORY='https://github.com/Agent-Eight/ClawShelf.git'
INSTALL_URL='https://raw.githubusercontent.com/Agent-Eight/ClawShelf/main/install.sh'
agent=; shared=0; reinstall=0
usage() {
  echo 'Usage: bash install.sh [--agent <id> | --global] [--reinstall]'
}
while (($#)); do
  case "$1" in
    --agent) [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { usage >&2; exit 2; }; agent=$2; shift 2 ;;
    --global) shared=1; shift ;;
    --reinstall) reinstall=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -z "$agent" || $shared == 0 ]] || { usage >&2; exit 2; }
step='checking prerequisites'
trap 'rc=$?; printf "Installation failed while %s (exit %s).\nRetry: curl -fsSL %q | bash -s --" "$step" "$rc" "$INSTALL_URL" >&2; if ((${#retry[@]})); then printf " %q" ${retry[@]+"${retry[@]}"} >&2; fi; printf "\n" >&2; exit "$rc"' ERR
retry=(); target=(); info_target=()
if [[ -n "$agent" ]]; then target=(--agent "$agent"); info_target=(--agent "$agent"); retry=(--agent "$agent"); fi
if ((shared)); then target=(--global); retry=(--global); fi
if ((reinstall)); then retry+=(--reinstall); fi
fail() { echo "$*" >&2; return 1; }
case "$(uname -s)" in Darwin|Linux) ;; *) fail 'Use macOS, Linux or WSL; native Windows is not supported.' ;; esac
for tool in openclaw node npm curl git; do
  command -v "$tool" >/dev/null || fail "Missing $tool. Install/configure OpenClaw with Node.js 22+ and npm, then retry."
done
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)' || fail 'Node.js 22+ is required. Update the Node installation used by OpenClaw.'
help=$(openclaw skills install --help)
[[ "$help" == *--agent* && "$help" == *--global* && "$help" == *--as* ]] || fail 'This OpenClaw version does not support skill installation; update OpenClaw.'
if [[ $(uname -s) == Darwin ]]; then
  command -v brew >/dev/null || fail 'Homebrew is required for QMD SQLite on macOS. Install Homebrew, then retry.'
  step='installing SQLite'
  if ! brew list sqlite >/dev/null 2>&1; then brew install sqlite; fi
fi
step='preparing user dependencies'
export CLAWSHELF_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/clawshelf"
mkdir -p "$CLAWSHELF_DATA_DIR"
CLAWSHELF_DATA_DIR=$(cd "$CLAWSHELF_DATA_DIR" && pwd -P)
export CLAWSHELF_DATA_DIR
export TMPDIR="${TMPDIR:-$CLAWSHELF_DATA_DIR/tmp}"
mkdir -p "$TMPDIR"
if command -v uv >/dev/null && uv --version >/dev/null; then
  export UV_BIN=$(command -v uv)
elif [[ -x "$CLAWSHELF_DATA_DIR/uv/bin/uv" ]] && "$CLAWSHELF_DATA_DIR/uv/bin/uv" --version >/dev/null; then
  export UV_BIN="$CLAWSHELF_DATA_DIR/uv/bin/uv"
else
  step='installing uv'
  download=$(mktemp "$TMPDIR/clawshelf-uv.XXXXXX")
  trap 'rm -f "${download:-}"' EXIT
  curl -fsSL https://astral.sh/uv/install.sh -o "$download"
  UV_INSTALL_DIR="$CLAWSHELF_DATA_DIR/uv/bin" UV_NO_MODIFY_PATH=1 sh "$download"
  export UV_BIN="$CLAWSHELF_DATA_DIR/uv/bin/uv"
fi
step='locating the target skill'
# OpenClaw resolves the active workspace and shared directory, including custom profiles.
report=$(openclaw skills list --json ${info_target[@]+"${info_target[@]}"})
expected=$(printf '%s' "$report" | node -e '
let s=""; process.stdin.on("data",d=>s+=d).on("end",()=>{
 const r=JSON.parse(s), p=require("path");
 const base=process.argv[1]==="1" ? r.managedSkillsDir : r.workspaceDir;
 if (!base || !p.isAbsolute(base)) process.exit(1);
 console.log(process.argv[1]==="1" ? p.join(base,"clawshelf") : p.join(base,"skills","clawshelf"));
});' "$shared")
if [[ ! -e "$expected" || $reinstall == 1 ]]; then
  step='installing the OpenClaw skill'
  force=(); if ((reinstall)); then force=(--force); fi
  if output=$(openclaw skills install "git:$REPOSITORY#main" --as clawshelf ${target[@]+"${target[@]}"} ${force[@]+"${force[@]}"}); then
    :
  else
    rc=$?; printf '%s\n' "$output" >&2; (exit "$rc")
  fi
  printf '%s\n' "$output"
  installed=$(printf '%s\n' "$output" | sed -n 's/^Installed clawshelf from git -> //p' | tail -n 1)
  [[ -n "$installed" && "$installed" == "$expected" ]] || fail 'OpenClaw did not confirm the expected installation directory. Inspect its output before retrying.'
fi
[[ -f "$expected/SKILL.md" && -f "$expected/scripts/run.sh" ]] || fail 'Existing skill lacks the one-step runtime. Use --reinstall to explicitly replace it.'
step='initializing Python and QMD'
bash "$expected/scripts/bootstrap.sh"
step='verifying extraction and keyword retrieval'
bash "$expected/scripts/run.sh" python "$expected/scripts/verify-install.py"
step='checking skill visibility'
info=$(openclaw skills info clawshelf --json ${info_target[@]+"${info_target[@]}"})
printf '%s' "$info" | node -e '
let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
 const r=JSON.parse(s),p=require("path");
 if(r.error || !r.filePath || p.dirname(r.filePath)!==process.argv[1] || !r.eligible || r.disabled || r.blockedByAgentFilter || r.blockedByAllowlist || r.modelVisible === false || r.commandVisible === false){
 console.error("Installed files are present, but the active agent cannot load this skill (or another copy shadows it). Check openclaw skills info clawshelf --json.");process.exit(1);
 }
});' "$expected"
printf '\nClawShelf 安装完成。\n安装位置：%s\n验证：技能加载、Python 提取、QMD 关键词检索通过。\n打开新的 OpenClaw 会话，然后运行：\n/clawshelf use /absolute/path/to/your-folder\n' "$expected"
