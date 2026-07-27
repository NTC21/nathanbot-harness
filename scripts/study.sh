#!/usr/bin/env bash
# study.sh — ingest external knowledge into nathanbot's wiki so it gets better at
# doing the owner's tasks. Give it a URL, a file, or piped/typed text; it distills the
# genuinely durable parts into a reference wiki page it can consult later.
#
#   nb study <url>
#   nb study <path/to/file>
#   nb study "some pasted text"
#   pbpaste | nb study
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
NB_CHECK=1 "$R/bin/claudew" >/dev/null 2>&1 || { echo "claude CLI not found" >&2; exit 1; }
B=$'\033[1m'; X=$'\033[0m'

src="${1:-}"; mode="text"; payload=""
if [ -n "$src" ]; then
  if [[ "$src" =~ ^https?:// ]]; then mode="url"; payload="$src"
  elif [ -f "$src" ]; then mode="file"; payload="$(cd "$(dirname "$src")" && pwd)/$(basename "$src")"
  else mode="text"; payload="$*"; fi
elif [ ! -t 0 ]; then mode="text"; payload="$(cat)"
fi
[ -z "${payload// }" ] && { echo "usage: nb study <url|file|text>" >&2; exit 1; }

case "$mode" in
  url)  srcline="Fetch and read this URL with WebFetch: $payload" ;;
  file) srcline="Read this local file: $payload" ;;
  text) srcline="Study this text:
---
$payload
---" ;;
esac

printf "${B}Studying (%s)...${X}\n" "$mode"

"$R/bin/claudew" -p "You are nathanbot studying external material to get BETTER at the owner's work.
$srcline

the owner's context: read $R/shared-memory/OVERVIEW.md and $R/wiki/pages/owner.md so you
judge relevance to HIM specifically (AI systems, agent harnesses, his stack, his ventures).

Extract only the DURABLE, reusable knowledge — techniques, patterns, mental models, facts
he'd want on tap later. Skip fluff, news, and anything time-bound.

WRITE a reference wiki page at $R/wiki/pages/<slug>.md following $R/wiki/SCHEMA.md
(type: reference, status: active). Include: what it is, the key takeaways, and a short
'How nathanbot should apply this to the owner's tasks' section. Link related pages with [[..]].
Add one line to $R/wiki/index.md and one to $R/wiki/log.md.

If the material has nothing durable worth keeping, say so plainly and write nothing.
Then print at most 3 lines: what you saved and where." \
  --permission-mode acceptEdits \
  --allowedTools "Read" "Write" "Edit" "WebFetch" "Grep" "Glob" 2>&1 | tail -20
