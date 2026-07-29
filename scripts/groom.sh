#!/usr/bin/env bash
# groom.sh — keep the task queue from rotting.
#
#   nb groom            report what's stale (changes nothing)
#   nb groom --apply    archive the stale items
#
# Rules (conservative — never touches anything ready or high-priority):
#   • priority 4-5, untouched > 30 days, not ready  -> archive
#   • blocked > 45 days                             -> archive (blocker went away or stopped mattering)
#   • needs-decision > 60 days                       -> archive (a decision not made in 2 months is a no)
#   • done > 90 days                                 -> compress into tasks/archive/done-YYYY-MM.md
# Archived tasks move to tasks/archive/ — recoverable, never deleted.
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
OPEN="$R/tasks/open"; DONE="$R/tasks/done"; ARCH="$R/tasks/archive"
mkdir -p "$ARCH"
APPLY=false; [ "${1:-}" = "--apply" ] && APPLY=true
NOW=$(date +%s)

B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; X=$'\033[0m'
fm() { grep -m1 "^$2:" "$1" 2>/dev/null | sed "s/^$2:[[:space:]]*//"; }
age_days() {
  local d; d=$(fm "$1" created)
  [ -z "$d" ] && { echo 0; return; }
  local ts; ts=$(date -j -f "%Y-%m-%d" "$d" +%s 2>/dev/null) || { echo 0; return; }
  echo $(( (NOW - ts) / 86400 ))
}

archive() {
  local f="$1" why="$2"
  printf "  %s%-12s%s %-52s %s%s%s\n" "$Y" "$(fm "$f" id)" "$X" "$(fm "$f" title | cut -c1-52)" "$D" "$why" "$X"
  if $APPLY; then
    printf '\narchived: %s — %s\n' "$(date +%Y-%m-%d)" "$why" >> "$f" \
      && mv "$f" "$ARCH/"
  fi
}

n=0
printf "%sStale in open queue%s\n" "$B" "$X"
for f in "$OPEN"/*.md; do
  [ -e "$f" ] || continue
  st=$(fm "$f" status); pr=$(fm "$f" priority); a=$(age_days "$f")
  case "$st" in
    ready|running) continue ;;  # never touch active work
  esac
  if [ "$st" = "blocked" ] && [ "$a" -gt 45 ]; then
    archive "$f" "blocked ${a}d"; n=$((n+1)); continue
  fi
  if [ "$st" = "needs-decision" ] && [ "$a" -gt 60 ]; then
    archive "$f" "undecided ${a}d — silence is a no"; n=$((n+1)); continue
  fi
  if [ "$st" = "looks-done" ] && [ "$a" -gt 60 ]; then
    archive "$f" "flagged done ${a}d ago, never confirmed"; n=$((n+1)); continue
  fi
  # looks-done is EXCLUDED from the P4/P5 rule below: evolve touched it, with
  # evidence, so "untouched" is false and archiving it would silently discard a
  # finish the owner was being asked to confirm. It gets the 60d rule above instead.
  if [ "$st" != "looks-done" ] && { [ "$pr" = "4" ] || [ "$pr" = "5" ]; } && [ "$a" -gt 30 ]; then
    archive "$f" "P${pr}, ${a}d untouched"; n=$((n+1)); continue
  fi
done
[ "$n" -eq 0 ] && printf "  %snothing stale%s\n" "$D" "$X"

# compress old completed work into a monthly digest
printf "\n%sCompleted work older than 90d%s\n" "$B" "$X"
c=0
for f in "$DONE"/*.md; do
  [ -e "$f" ] || continue
  a=$(age_days "$f")
  [ "$a" -le 90 ] && continue
  c=$((c+1))
  if $APPLY; then
    # && not ; — this file is set -uo pipefail with no -e, so a failed append
    # used to delete the task anyway and the digest line was simply lost.
    # An empty created: also put everything in a file literally named "done-.md".
    mon=$(fm "$f" created | cut -c1-7); [ -n "$mon" ] || mon=undated
    printf -- '- %s %s\n' "$(fm "$f" id)" "$(fm "$f" title)" >> "$ARCH/done-$mon.md" \
      && rm "$f"
  fi
done
[ "$c" -eq 0 ] && printf "  %snone%s\n" "$D" "$X" || printf "  %s task(s) %s\n" "$c" "$($APPLY && echo 'compressed into monthly digests' || echo 'would be compressed')"

printf "\n%sQueue health%s\n" "$B" "$X"
printf "  open:     %s\n" "$(ls "$OPEN"/*.md 2>/dev/null | wc -l | tr -d ' ')"
printf "  done:     %s\n" "$(ls "$DONE"/*.md 2>/dev/null | wc -l | tr -d ' ')"
printf "  archived: %s\n" "$(ls "$ARCH"/*.md 2>/dev/null | wc -l | tr -d ' ')"

if ! $APPLY && [ $((n + c)) -gt 0 ]; then
  printf "\n%sreport only — run 'nb groom --apply' to archive%s\n" "$D" "$X"
fi
