#!/usr/bin/env bash
# digest.sh — turn the owner's daily Obsidian notes (+ recent session notes) into system
# state: file action items as tasks, capture durable facts to the wiki. Runs nightly.
# It NEVER edits or deletes his notes — read-only on the journal, write-only to the system.
#
#   nb digest            process today's + yesterday's daily note
#   nb digest --show     just print what would be processed, no AI
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
DAILY="$R/wiki/daily"
B=$'\033[1m'; D=$'\033[2m'; X=$'\033[0m'

today="$(date +%F)"; yest="$(date -v-1d +%F 2>/dev/null || date -d 'yesterday' +%F)"
notes=()
for d in "$today" "$yest"; do [ -f "$DAILY/$d.md" ] && notes+=("$DAILY/$d.md"); done

if [ "${1:-}" = "--show" ]; then
  printf "${B}Would digest:${X}\n"
  if [ ${#notes[@]} -eq 0 ]; then echo "  (no daily notes for $today / $yest — will still mine chat/feedback)"; else printf '  %s\n' "${notes[@]}"; fi
  exit 0
fi
# NO early-exit on missing daily notes: chat/voice conversation is mined regardless,
# otherwise everything the owner says to the operator evaporates unless he journals.
NB_CHECK=1 "$R/bin/claudew" >/dev/null 2>&1 || { echo "claude CLI not found" >&2; exit 1; }

printf "${B}Digesting %d daily note(s) + conversation...${X}\n" "${#notes[@]}"
list=""; for n in "${notes[@]}"; do list+="- $n"$'\n'; done
[ -z "$list" ] && list="(no daily notes today — mine the chat history and recent session notes only)"

NB_FEEDBACK_SRC=digest "$R/bin/claudew" -p "You are nathanbot processing the owner's daily journal notes into system state.

READ these daily notes (read-only — never edit or delete them):
$list
Also skim the newest dated note in $R/workspace*/memory/ and the recent operator chat
$R/tasks/.chat.json for anything unrecorded.

the owner's context: $R/shared-memory/OVERVIEW.md, $R/wiki/pages/owner.md.

Do THREE things:
1. ACTION ITEMS — anything implying a task ('need to', 'todo', 'follow up', unchecked
   '- [ ]' lines). For each NEW one, run:  $R/bin/nb add \"<the task>\"
   First check $R/bin/nb status and skip anything already queued. Don't duplicate.
2. DURABLE FACTS — decisions, preferences, project facts worth remembering long-term.
   Append to the right $R/wiki/pages/*.md, or propose a memory per $R/wiki/storage-policy.md.
   Ignore fleeting mood/journal — only what changes how you should work for him.
3. CORRECTIONS — if he expressed how nathanbot/you should behave DIFFERENTLY ('no, do X',
   'stop doing Y', 'next time', 'you should', 'be more/less'), capture each verbatim-ish via:
     $R/bin/nb feedback \"<the correction>\"
   These are the strongest learning signal — don't paraphrase away the point. Skip if none.

Print a terse summary: N tasks filed, M facts saved, K corrections captured." \
  --permission-mode acceptEdits \
  --allowedTools "Read" "Write" "Edit" "Grep" "Glob" "Bash($R/bin/nb:*)" 2>&1 | tail -25

# keep the cross-harness promise: captured memory rides to the remote nightly,
# so other machines/harnesses actually see it (AGENTS.md: commit+push by default)
# stderr is kept and the rc is reported: `|| true` on top of cmd_sync's own
# swallowed error meant a failing nightly push was invisible from both ends.
"$R/bin/nb" sync "chore: nightly digest write-back" >/dev/null \
  || echo "digest: nightly sync failed (rc=$?) — nathanbot is not reaching the remote" >&2
