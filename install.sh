#!/usr/bin/env bash
# gadoc installer: links the gadoc skills into grok and Antigravity CLI (agy).
#   bash install.sh              install for grok and agy
#   bash install.sh --grok-only  | --agy-only
#   bash install.sh --uninstall  remove the links this script created
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS=(gadoc gadoc-trim)
GROK_DIR="${GROK_HOME:-$HOME/.grok}/skills"
AGY_DIR="$HOME/.gemini/config/skills"

targets=("$GROK_DIR" "$AGY_DIR")
mode=install
for arg in "$@"; do
  case "$arg" in
    --grok-only) targets=("$GROK_DIR") ;;
    --agy-only) targets=("$AGY_DIR") ;;
    --uninstall) mode=uninstall ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

for dir in "${targets[@]}"; do
  for s in "${SKILLS[@]}"; do
    link="$dir/$s"
    src="$REPO/skills/$s"
    if [[ $mode == uninstall ]]; then
      if [[ -L $link && "$(readlink "$link")" == "$src" ]]; then
        rm "$link" && echo "removed  $link"
      fi
      continue
    fi
    mkdir -p "$dir"
    if [[ -e $link || -L $link ]] && [[ "$(readlink "$link" 2>/dev/null)" != "$src" ]]; then
      echo "skip     $link (exists and is not a gadoc link; move it away first)" >&2
      continue
    fi
    ln -sfn "$src" "$link"
    echo "linked   $link -> $src"
  done
done

if [[ $mode == install ]]; then
  echo
  echo "Done. Start a new session: grok \"/gadoc audit .\" | agy \"gadoc audit .\""
fi
