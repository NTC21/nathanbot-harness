#!/usr/bin/env bash
# rundue.sh — run a scheduled job only if its last scheduled occurrence was missed.
#
#   rundue.sh <name> <hour> <minute> <weekday|-> <day|-> -- <cmd...>
#
# launchd replays a missed StartCalendarInterval across sleep, but NOT across a
# power-off. So every calendar job also gets RunAtLoad=true, and this wrapper
# decides whether that boot-time firing is a real catch-up or a no-op:
#
#   run if   last-scheduled-occurrence-at-or-before-now  >  last successful run
#
# That makes the normal on-time firing run (stamp is older), a boot after a
# missed window catch up, and a boot inside an already-satisfied window do
# nothing. The stamp is written only when the job exits 0, so a failed run is
# retried at the next load instead of being silently marked done.
#
# NB_FORCE=1 skips the check entirely.
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"

# Belt to claudew's suspenders. Every calendar plist routes through this file, so
# a job that shells out to a bare `claude` against the AGENTS.md rule is still
# covered — and this holds for the plists already on disk, with no regeneration.
export NB_UNATTENDED=1

name="$1"; hour="$2"; minute="$3"; weekday="$4"; day="$5"; shift 5
[ "${1:-}" = "--" ] && shift

stamp="$R/tasks/state/$name.last"
mkdir -p "$R/tasks/state"

occ="$(python3 "$R/scripts/lastdue.py" --hour "$hour" --minute "$minute" \
        --weekday "$weekday" --day "$day")" || exit 0

if [ "${NB_FORCE:-0}" != "1" ]; then
  prev="$(cat "$stamp" 2>/dev/null || echo '')"
  # string compare is safe: both are ISO-8601 local timestamps, zero-padded
  if [ -n "$prev" ] && [ ! "$occ" \> "$prev" ]; then
    exit 0
  fi
fi

"$@"
rc=$?
[ $rc -eq 0 ] && printf '%s\n' "$occ" > "$stamp"
exit $rc
