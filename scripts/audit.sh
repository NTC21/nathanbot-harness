#!/usr/bin/env bash
# audit.sh — check memory wiring and staleness across nathanbot.
# Run periodically (Duke runs the equivalent as a recurring "workspace audit").
# Read-only: reports, never edits.
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
cd "$R"
TODAY=$(date +%s)
warn=0

hdr() { printf "\n\033[1m%s\033[0m\n" "$1"; }
bad() { printf "  ⚠️  %s\n" "$1"; warn=$((warn+1)); }
ok()  { printf "  ✅ %s\n" "$1"; }

hdr "1. Bounded core"
n=$(wc -c < shared-memory/OVERVIEW.md)
if [ "$n" -gt 2600 ]; then bad "OVERVIEW.md is $n chars — over budget. Move detail to wiki/pages/."
else ok "OVERVIEW.md $n chars (within budget)"; fi

hdr "2. Hermes bridge caps"
u=$(wc -c < hermes/USER.md 2>/dev/null || echo 0)
m=$(wc -c < hermes/MEMORY.md 2>/dev/null || echo 0)
[ "$u" -gt 1375 ] && bad "hermes/USER.md $u chars > 1375 cap" || ok "hermes/USER.md $u chars"
[ "$m" -gt 2200 ] && bad "hermes/MEMORY.md $m chars > 2200 cap" || ok "hermes/MEMORY.md $m chars"

hdr "3. Entry-doc wiring (harness-agnostic)"
grep -q 'AGENTS.md' CLAUDE.md 2>/dev/null && ok "CLAUDE.md points to AGENTS.md" || bad "CLAUDE.md does not point to AGENTS.md"
grep -q 'AGENTS.md' .cursorrules 2>/dev/null && ok ".cursorrules points to AGENTS.md" || bad ".cursorrules missing/not pointing"
[ "$(wc -l < CLAUDE.md)" -lt 15 ] && ok "CLAUDE.md is thin (pointer, not duplicate)" || bad "CLAUDE.md is fat — content may be duplicating AGENTS.md"

hdr "4. Orphan wiki pages (no inbound or outbound links)"
for f in wiki/pages/*.md; do
  [ -e "$f" ] || continue
  b=$(basename "$f" .md)
  out=$(grep -c '\[\[' "$f" 2>/dev/null; true)   # grep -c prints 0 itself; '|| echo 0' double-emits "0\n0"
  in=$(grep -rl "\[\[$b\]\]" wiki/ --include='*.md' 2>/dev/null | grep -v "$f" | wc -l | tr -d ' ')
  [ "$out" -eq 0 ] && bad "$b has no outbound links"
  [ "$in" -eq 0 ] && bad "$b has no inbound links (invisible in graph)"
done
[ "$warn" -eq 0 ] && ok "all pages linked"

hdr "5. Stale wiki pages (updated: > 30 days)"
for f in wiki/pages/*.md; do
  [ -e "$f" ] || continue
  d=$(grep -m1 '^updated:' "$f" | awk '{print $2}')
  [ -z "$d" ] && { bad "$(basename "$f") missing 'updated:' frontmatter"; continue; }
  ts=$(date -j -f "%Y-%m-%d" "$d" +%s 2>/dev/null) || continue
  days=$(( (TODAY - ts) / 86400 ))
  # 30, not 90. Nine of nineteen pages had `updated:` behind their real last-edit
  # date, so at 90 this could not fire — a check with a threshold longer than the
  # drift it measures is decoration.
  [ "$days" -gt 30 ] && bad "$(basename "$f" .md) not updated in $days days"
done

hdr "6. Index coverage"
for f in wiki/pages/*.md; do
  [ -e "$f" ] || continue
  b=$(basename "$f" .md)
  grep -q "\[\[$b\]\]" wiki/index.md || bad "$b not listed in wiki/index.md"
done

hdr "7. Write-back freshness"
last=$(ls -t workspace*/memory/*.md 2>/dev/null | grep -v '.gitkeep' | head -1)
if [ -z "$last" ]; then bad "no dated session notes yet — write-back not happening"
else
  d=$(basename "$last" .md)
  ts=$(date -j -f "%Y-%m-%d" "$d" +%s 2>/dev/null) && {
    days=$(( (TODAY - ts) / 86400 ))
    # 3, not 14. AGENTS.md requires a note per meaningful session; exactly ONE has
    # ever been written, and at 14 days this printed a green tick over that.
    [ "$days" -gt 3 ] && bad "last session note is $days days old ($last) — AGENTS.md wants one per session" || ok "last session note $days days old"
  }
fi

hdr "8. Global context wiring"
G="$HOME/.claude/CLAUDE.md"
if [ -f "$G" ]; then
  grep -q 'nathanbot' "$G" && ok "global CLAUDE.md points to nathanbot" || bad "global CLAUDE.md exists but does not reference nathanbot"
  gn=$(wc -c < "$G")
  [ "$gn" -gt 4000 ] && bad "global CLAUDE.md is $gn chars — loads every session, trim it" || ok "global CLAUDE.md $gn chars (loads every session)"
else
  bad "no ~/.claude/CLAUDE.md — sessions outside a project get no nathanbot context"
fi

hdr "9. Secret leakage"
if git ls-files 2>/dev/null | grep -qE '(^|/)\.env$|\.pem$|\.p8$|AuthKey_'; then
  bad "secret-looking files are TRACKED in this repo"
else ok "no tracked secrets"; fi

hdr "10. Telemetry integrity"
tf="tasks/.telemetry.jsonl"
if [ -f "$tf" ]; then
  broken=$(python3 -c "
import json
b=0
for l in open('$tf'):
    l=l.strip()
    if l:
        try: json.loads(l)
        except Exception: b+=1
print(b)" 2>/dev/null || echo '?')
  [ "$broken" = 0 ] && ok "usage log clean (all lines parse)" \
    || bad "$broken malformed line(s) in .telemetry.jsonl — evolve/digest read garbage"
else ok "no telemetry yet"; fi

hdr "11. Wiki hygiene"
vaults=$(find . -name .obsidian -not -path '*/node_modules/*' | wc -l | tr -d ' ')
[ "$vaults" = 1 ] && ok "one Obsidian vault (wiki/)" \
  || bad "$vaults Obsidian vaults on this tree — nested vaults split the graph; keep only wiki/"
# grep -c prints 0 AND exits 1 when there are no matches, so `|| echo '?'` used to
# emit both — "0\n?" — and the clean case rendered as a warning reading "⚠️ 0 ?".
wikiprobs=$(python3 scripts/wiki_index.py --lint 2>/dev/null | grep -c ':' || true)
[ "$wikiprobs" = 0 ] && ok "wiki clean (schema, links, index in sync)" \
  || bad "$wikiprobs wiki problem(s) — run 'nb wiki lint'"

hdr "12. Specialist agents"
# Every agent named in the operator's roster must EXIST, and no agent file may
# carry the <root> placeholder — nothing substitutes it (agent files don't go
# through build_operator_prompt), so it reached the model literally and any path
# built from it was wrong. Four of six files had it.
missing=0
for a in $(sed -n '/^YOUR SPECIALIST TEAM/,/^Routing rules:/p' prompts/operator.md \
           | sed -n 's/^- \([a-z-]*\) *—.*/\1/p'); do
  [ -f ".claude/agents/$a.md" ] || { bad "operator.md routes to '$a' but .claude/agents/$a.md is missing"; missing=1; }
done
ph=$(grep -rl '<root>' .claude/agents/ 2>/dev/null | tr '\n' ' ')
[ -n "$ph" ] && bad "unsubstituted <root> in: $ph"
[ "$missing" = 0 ] && [ -z "$ph" ] && ok "roster intact ($(ls .claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ') agents, no placeholders)"

hdr "13. Cost visibility"
# A model the price table cannot price would otherwise contribute $0 to every
# report — a number that looks like an answer. Extraction is keyed on the CLI
# version, so this fires on the first run after an upgrade that adds a model.
up=$(python3 scripts/usage.py --days 7 2>/dev/null | grep -c 'unpriced' || true)
[ "$up" = 0 ] && ok "every model in the last 7d is priceable" \
  || bad "unpriced model(s) in the last 7d — 'nb usage' is undercounting; see scripts/lib/transcripts.py"

hdr "Memory vs reality (staleness)"
# Structure checks above prove the wiring; this proves the CLAIMS still hold.
# Confidently-wrong memory is worse than missing memory — a later session acts on it.
staleout=$(python3 "$R/scripts/stale.py" --quiet 2>/dev/null)
if [ -z "$staleout" ]; then ok "no stale references — memory matches reality"
else
  n=$(printf '%s\n' "$staleout" | grep -cE '^\s{4}\S+:[0-9]+')
  bad "$n stale reference(s) — run 'nb stale' for detail"
fi

printf "\n\033[1m%s warning(s)\033[0m\n" "$warn"
