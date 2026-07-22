#!/usr/bin/env bash
# watch.sh — nathanbot's ambient awareness (OpenJarvis monitor_operative pattern).
# READ-ONLY. Checks a few high-signal conditions and surfaces ONLY what's NEW,
# through deliver.sh (notification / iMessage / Discord). Silent when nothing's up.
# A dedup "memory" (tasks/.watch-state/) stops it re-nagging the same thing.
#
#   nb watch          run checks, notify on anything new   (scheduled every 30 min)
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
mark() { $dry || : > "$STATE/$1"; }
find "$STATE" -type f -mtime +1 -delete 2>/dev/null || true   # expire day-old marks

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

# ── 2. Repos left with uncommitted work ──────────────────────────────────────
for d in "$CODE_ROOT"/*/; do
  [ -d "${d}.git" ] || continue
  [ -n "$(git -C "$d" status --porcelain 2>/dev/null)" ] || continue
  name=$(basename "$d"); key="dirty-$name"
  seen "$key" || { findings+=("Uncommitted work sitting in $name"); mark "$key"; }
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
