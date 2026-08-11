#!/usr/bin/env bash
# watch.sh — nathanbot's ambient awareness (OpenJarvis monitor_operative pattern).
# READ-ONLY. Checks a few high-signal conditions and surfaces ONLY what's NEW,
# through deliver.sh (notification / iMessage / Discord). Silent when nothing's up.
# A dedup "memory" (tasks/.watch-state/) stops it re-nagging the same thing.
#
#   nb watch          run checks, notify on anything new   (scheduled every 2 hours)
#   nb watch --dry    print findings, change nothing
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$R/tasks/.watch-state"
mkdir -p "$STATE"
dry=false; [ "${1:-}" = "--dry" ] && dry=true
CODE_ROOT="${CODE_ROOT:-$HOME/Projects}"

# quiet hours — no ambient pings overnight
h=$(date +%H)
if [ "$h" -ge 23 ] || [ "$h" -lt 7 ]; then $dry || exit 0; fi

seen() { [ -f "$STATE/$1" ]; }
# seen(), but only counting marks younger than $2 days — the re-fire clock for
# keys whose interval is longer than the daily reaper below. mark() truncates,
# which refreshes mtime, so the mark's own timestamp is the clock.
seen_within() { [ -f "$STATE/$1" ] && [ -z "$(find "$STATE/$1" -mtime +"$2" 2>/dev/null)" ]; }
mark() { $dry || : > "$STATE/$1"; }
# expire day-old marks, EXCEPT the weekly dirty-repo ones — a 1-day expiry on a
# week-scoped key would just re-fire the same repo every day
find "$STATE" -type f -mtime +1 ! -name 'dirty-*' -delete 2>/dev/null || true
# dirty-* marks are gated by seen_within, not by this reaper; +8 only collects
# marks for repos that have gone away entirely.
find "$STATE" -type f -mtime +8 -name 'dirty-*' -delete 2>/dev/null || true

findings=()

# ── 1. Imminent meeting (starts within 30 min) ───────────────────────────────
imminent=$(python3 - "$R" <<'PY' 2>/dev/null || true
import subprocess, sys, re
from datetime import datetime, timezone
R = sys.argv[1]
try:
    out = subprocess.run(["python3", f"{R}/scripts/google/gcalendar.py", "agenda", "--all", "--days", "1"],
                         capture_output=True, text=True, timeout=20).stdout
except Exception:
    sys.exit(0)
now = datetime.now(timezone.utc)
for line in out.splitlines():
    m = re.match(r"\s+(\S+)\s+\[\w+\]\s+(.*)", line)
    if not m:
        continue
    ts, title = m.groups()
    try:
        start = datetime.fromisoformat(ts)
    except Exception:
        continue
    mins = (start - now).total_seconds() / 60
    if 0 < mins <= 30:
        print(f"{int(mins)}|{title.split('  @')[0].strip()}|{ts}")
        break
PY
)
spoken=""
if [ -n "$imminent" ]; then
  mins=${imminent%%|*}; rest=${imminent#*|}; title=${rest%%|*}; ts=${rest##*|}
  key="mtg-$ts"
  # imminent meetings are worth SAYING out loud (Jarvis), not just a notification
  seen "$key" || { findings+=("Meeting in ${mins}m: $title"); mark "$key"; spoken="Sir, you have $title in ${mins} minutes."; }
fi

# ── 2. Repos with STALE uncommitted work ─────────────────────────────────────
# the owner works dirty on purpose, so "this repo has changes" is not news — it was
# firing on every active repo daily, including one triggered by a single
# untracked scratch file. The only version of this worth a ping is work that
# looks abandoned and at risk of being lost, so:
#   - untracked-only dirt is ignored (scratch files, build output)
#   - the repo must have gone quiet for DIRTY_DAYS since its last commit
#   - at most DIRTY_MAX repos per run, and once a week per repo, not once a day
dirty_days="${NB_DIRTY_DAYS:-3}"
dirty_max="${NB_DIRTY_MAX:-2}"
dirty_every="${NB_DIRTY_EVERY_DAYS:-7}"   # re-fire interval per repo
dirty_n=0
for d in "$CODE_ROOT"/*/; do
  [ "$dirty_n" -ge "$dirty_max" ] && break
  [ -d "${d}.git" ] || continue
  tracked=$(git -C "$d" status --porcelain 2>/dev/null | grep -cv '^??' || true)
  [ "${tracked:-0}" -gt 0 ] || continue
  last=$(git -C "$d" log -1 --format=%ct 2>/dev/null) || continue
  [ -n "$last" ] || continue
  age=$(( ( $(date +%s) - last ) / 86400 ))
  [ "$age" -ge "$dirty_days" ] || continue
  # No date in the key. It used to carry $(date +%Y-%V), and %V is an ISO week
  # number: a repo flagged on a Sunday — the last day of an ISO week — got a
  # brand-new key on Monday and fired again the next day, against the stated
  # "once a week per repo" above. (%Y paired with %V was a second bug of the same
  # kind; the ISO week-year is %G, so the key also broke across New Year.) The
  # interval is now the mark file's own mtime.
  name=$(basename "$d"); key="dirty-$name"
  seen_within "$key" "$dirty_every" || {
    findings+=("$name: $tracked uncommitted file(s), no commit in ${age}d")
    mark "$key"; dirty_n=$((dirty_n+1))
  }
done

# ── 3. VIP unread email (opt-in: one sender per line in the watchlist) ────────
vip="$HOME/.secrets/nathanbot/vip_senders"
if [ -f "$vip" ]; then
  while IFS= read -r sender; do
    [ -z "${sender// }" ] && continue
    n=$(python3 "$R/scripts/google/gmail.py" --account personal search "is:unread from:$sender" --limit 5 2>/dev/null | grep -cE '^\s*[0-9]+\.|^\s*-|@' || true)
    [ "${n:-0}" -gt 0 ] || continue
    key="vip-$sender-$(date +%F)"
    seen "$key" || { findings+=("Unread from $sender"); mark "$key"; }
  done < "$vip"
fi

# ── surface only if there's something new ────────────────────────────────────
[ ${#findings[@]} -eq 0 ] && exit 0
msg=$(printf '%s\n' "${findings[@]}")
if $dry; then printf '%s\n' "$msg"; [ -n "$spoken" ] && echo "(would speak: $spoken)"; exit 0; fi
"$R/scripts/deliver.sh" "nathanbot noticed" "$msg" >/dev/null 2>&1 || true
# only imminent meetings get spoken aloud — everything else is a quiet notification
# detached so the audio survives launchd killing our process group on exit
if [ -n "$spoken" ]; then . "$R/scripts/lib/detach.sh"; nb_detach "$R/scripts/speak.sh" "$spoken"; fi
