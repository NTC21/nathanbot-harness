#!/usr/bin/env bash
# schedule.sh — install/remove launchd jobs so nathanbot runs on its own.
#
#   nb schedule install    install all jobs
#   nb schedule status     show what's loaded and when it last ran
#   nb schedule remove     unload everything
#
# Jobs installed:
#   brief   daily  07:30   — reads + reports. Never changes anything.
#   tidy    weekly Sun 09:00 — REPORT ONLY by default (no --apply).
#   evolve  weekly Mon 08:00 — proposes improvements as needs-decision tasks.
#   scout   monthly 1st 08:30 — researches new tools, writes wiki pages.
#
# Nothing scheduled ever pushes code or merges. Execution (`nb run`) stays manual
# until you explicitly add it.
set -euo pipefail

R="$(cd "$(dirname "$0")/.." && pwd)"
NB="$R/bin/nb"
LA="$HOME/Library/LaunchAgents"
PREFIX="com.nathanbot"
mkdir -p "$LA" "$R/tasks/logs"

mkjob() {
  local name="$1" hour="$2" minute="$3" extra="$4" args="$5"
  local plist="$LA/$PREFIX.$name.plist"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.$name</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>$NB $args</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$hour</integer>
    <key>Minute</key><integer>$minute</integer>
$extra
  </dict>
  <key>StandardOutPath</key><string>$R/tasks/logs/$name.log</string>
  <key>StandardErrorPath</key><string>$R/tasks/logs/$name.err</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
EOF
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist" 2>/dev/null && echo "  installed: $name"
}

case "${1:-install}" in
  install)
    echo "Installing nathanbot scheduled jobs..."
    mkjob brief  7  30 ""                              "brief --quiet"
    mkjob tidy   9   0 "    <key>Weekday</key><integer>0</integer>" "tidy"
    mkjob evolve 8   0 "    <key>Weekday</key><integer>1</integer>" "evolve"
    mkjob groom  9  30 "    <key>Weekday</key><integer>0</integer>" "groom"
    mkjob learn  8  30 "    <key>Weekday</key><integer>1</integer>" "learn"
    mkjob scout  8  30 "    <key>Day</key><integer>1</integer>"     "scout"
    echo
    echo "Done. nathanbot now runs on its own:"
    echo "  brief   daily 07:30      (notification + tasks/.brief-*.md)"
    echo "  tidy    Sundays 09:00    (report only)"
    echo "  evolve  Mondays 08:00    (proposals -> needs-decision tasks)"
    echo "  scout   1st of month     (new tools -> wiki pages)"
    echo
    echo "Nothing scheduled pushes code or merges. 'nb run' stays manual."
    ;;
  status)
    echo "Loaded jobs:"
    launchctl list 2>/dev/null | grep "$PREFIX" || echo "  none"
    echo
    echo "Recent output:"
    for f in "$R"/tasks/logs/*.log; do
      [ -e "$f" ] || continue
      printf "  %-12s %s\n" "$(basename "$f" .log)" "$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f" 2>/dev/null)"
    done
    ;;
  remove)
    for n in brief tidy evolve scout groom learn; do
      p="$LA/$PREFIX.$n.plist"
      [ -e "$p" ] && launchctl unload "$p" 2>/dev/null; rm -f "$p" && echo "  removed: $n"
    done
    ;;
  *) echo "usage: nb schedule [install|status|remove]"; exit 1 ;;
esac
