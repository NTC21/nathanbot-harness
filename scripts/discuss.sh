#!/usr/bin/env bash
# discuss.sh — talk freely; the system interviews you and absorbs what it learns.
#
#   nb discuss                    open-ended: it asks what's on your mind
#   nb discuss "content strategy" start on a topic
#   nb discuss --review           show what was learned recently, before writing more
#
# Ends by proposing memory writes, showing them, and asking before committing.
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"

if [ "${1:-}" = "--review" ]; then
  echo "Recently learned:"
  ls -t "$R"/workspace*/memory/*.md 2>/dev/null | grep -v gitkeep | head -5 | while read -r f; do
    echo "  ${f#$R/}"; sed -n '3,7p' "$f" | sed 's/^/    /'
  done
  exit 0
fi

TOPIC="${*:-}"
# This one is INTERACTIVE, so it execs the real binary rather than going through
# claudew — claudew buffers stdout/stderr into temp files and prints at exit,
# which is right for `-p` and fatal for a conversation. Use claudew only to
# resolve the path, so there is still exactly one resolver.
CLAUDE_BIN="$(NB_CHECK=1 "$R/bin/claudew")" \
  || { echo "claude CLI not found" >&2; exit 1; }

PROMPT="You are interviewing the owner to build up nathanbot's memory of him. This is a CONVERSATION,
not a form. Your job is to learn things worth keeping.

BEFORE ASKING ANYTHING, read so you don't re-ask what's already known:
- $R/shared-memory/OVERVIEW.md
- $R/wiki/pages/owner.md
- $R/wiki/index.md (then any page relevant to the topic)
- the relevant $R/workspace-*/MEMORY.md

$( [ -n "$TOPIC" ] && echo "TOPIC: $TOPIC" || echo "No topic given — open by asking what's on his mind, or offer 2-3 gaps you noticed in memory that would be most valuable to fill." )

HOW TO INTERVIEW:
- One question at a time. This is a conversation, not a questionnaire.
- Follow the interesting thread. If he says something surprising, dig there.
- Ask WHY, not just what. 'I use X' is thin; 'I use X because Y burned me' is durable.
- Notice contradictions with existing memory and ask about them — memory going stale is
  the main failure mode.
- Don't ask what you can read. Never ask something already in OVERVIEW.md or the wiki.
- Reflect back what you heard in your own words before moving on, so errors surface early.
- If he goes quiet or short, offer a concrete guess to react to rather than a blank prompt.

WHEN THE CONVERSATION WINDS DOWN (he says done/thanks/that's it, or the thread is exhausted):
1. Summarize what you learned, grouped by where it belongs.
2. Propose specific writes following $R/wiki/SCHEMA.md and $R/wiki/storage-policy.md:
   - durable cross-workspace facts -> $R/wiki/pages/<slug>.md (+ index.md line, log.md entry)
   - curated single-domain facts -> the right $R/workspace-*/MEMORY.md (bump Last updated)
   - session notes -> $R/workspace/memory/$(date +%Y-%m-%d).md (append 2-5 lines)
   - operator-wide identity/preferences -> $R/shared-memory/OVERVIEW.md
     (BOUNDED ~2000 chars — if it would overflow, move detail to the wiki and link instead)
3. SHOW him exactly what you plan to write. Ask before writing.
4. After he approves, write the files, then 'cd $R && git add -A && git commit'.

RULES:
- Every wiki page needs frontmatter per SCHEMA.md and at least one [[link]], or it is
  invisible in the graph.
- Facts live in exactly ONE canonical place; everything else links to it.
- Do not invent. If unsure whether you understood, ask.
- Do not write anything inferred from his EMAIL into memory without explicit permission —
  see $R/config/permissions.json.
- Be terse. He runs a compression prompt and dislikes filler."

# The default is built OUTSIDE the quotes on purpose. bash treats a single quote
# inside "${var:-word}" as a real quote character, so the apostrophe in the old
# default ("Let's talk...") opened a string that never closed — `bash -n` failed
# and `nb discuss` had never once run.
: "${TOPIC:=Read my memory first, then start a conversation with me.}"
exec "$CLAUDE_BIN" --append-system-prompt "$PROMPT" "$TOPIC"
