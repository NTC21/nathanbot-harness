#!/usr/bin/env bash
# wiki.sh — keep the Obsidian wiki honest.
#
#   nb wiki index    regenerate wiki/index.md from page frontmatter (grouped by type:)
#   nb wiki lint     report schema violations: bad frontmatter, orphans, dead links
#
# The index is GENERATED, not hand-maintained — a hand-kept index drifts from reality
# and then lies to every agent that reads it.
set -uo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${1:-index}" in
  index) python3 "$R/scripts/wiki_index.py" --write ;;
  lint)  python3 "$R/scripts/wiki_index.py" --lint ;;
  check) python3 "$R/scripts/wiki_index.py" --check ;;
  *) echo "usage: nb wiki <index|lint|check>" >&2; exit 2 ;;
esac
