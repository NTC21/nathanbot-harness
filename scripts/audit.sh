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
  out=$(grep -c '\[\[' "$f" 2>/dev/null || echo 0)
  in=$(grep -rl "\[\[$b\]\]" wiki/ --include='*.md' 2>/dev/null | grep -v "$f" | wc -l | tr -d ' ')
  [ "$out" -eq 0 ] && bad "$b has no outbound links"
  [ "$in" -eq 0 ] && bad "$b has no inbound links (invisible in graph)"
done
[ "$warn" -eq 0 ] && ok "all pages linked"

hdr "5. Stale wiki pages (updated: > 90 days)"
for f in wiki/pages/*.md; do
  [ -e "$f" ] || continue
  d=$(grep -m1 '^updated:' "$f" | awk '{print $2}')
  [ -z "$d" ] && { bad "$(basename "$f") missing 'updated:' frontmatter"; continue; }
  ts=$(date -j -f "%Y-%m-%d" "$d" +%s 2>/dev/null) || continue
  days=$(( (TODAY - ts) / 86400 ))
  [ "$days" -gt 90 ] && bad "$(basename "$f" .md) not updated in $days days"
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
    [ "$days" -gt 14 ] && bad "last session note is $days days old ($last)" || ok "last session note $days days old"
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

printf "\n\033[1m%s warning(s)\033[0m\n" "$warn"
