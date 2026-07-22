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
  <key>AbandonProcessGroup</key><true/>
</dict>
</plist>
EOF
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist" 2>/dev/null && echo "  installed: $name"
}

case "${1:-install}" in
  install)
    echo "Installing nathanbot scheduled jobs..."
    mkjob brief  7  30 ""                              "brief --quiet --deliver --speak"
    mkjob digest 22  0 ""                              "digest"
    mkjob sync   22 45 ""                              "sync"
    mkjob tidy   9   0 "    <key>Weekday</key><integer>0</integer>" "tidy"
    mkjob evolve 8   0 "    <key>Weekday</key><integer>1</integer>" "evolve --apply"
    mkjob groom  9  30 "    <key>Weekday</key><integer>0</integer>" "groom --apply"
    mkjob learn  8  30 "    <key>Weekday</key><integer>1</integer>" "learn --apply"
    mkjob scout  8  30 "    <key>Day</key><integer>1</integer>"     "scout"
    # watcher runs on a 30-min interval (not a clock time); watch.sh self-mutes 23:00–07:00
    cat > "$LA/$PREFIX.watch.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.watch</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>-lc</string><string>$NB watch</string></array>
  <key>StartInterval</key><integer>1800</integer>
  <key>StandardOutPath</key><string>$R/tasks/logs/watch.log</string>
  <key>StandardErrorPath</key><string>$R/tasks/logs/watch.err</string>
  <key>RunAtLoad</key><false/>
  <key>AbandonProcessGroup</key><true/>
</dict>
</plist>
EOF
    launchctl unload "$LA/$PREFIX.watch.plist" 2>/dev/null || true
    launchctl load "$LA/$PREFIX.watch.plist" 2>/dev/null && echo "  installed: watch"
    echo
    echo "Done. nathanbot now runs on its own:"
    echo "  brief   daily 07:30      (notification + tasks/.brief-*.md)"
    echo "  digest  daily 22:00      (daily notes -> tasks + wiki facts)"
    echo "  watch   every 30 min     (ambient: meetings, dirty repos, VIP mail)"
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
  install-jarvis)
    # Separate from `install` because the hands-free daemon needs a Microphone grant.
    # First run `nb jarvis once` from Terminal to trigger the mic prompt, THEN this.
    cat > "$LA/$PREFIX.jarvis.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.jarvis</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>-lc</string><string>$NB jarvis start</string></array>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$R/tasks/logs/jarvis.log</string>
  <key>StandardErrorPath</key><string>$R/tasks/logs/jarvis.err</string>
</dict>
</plist>
EOF
    launchctl unload "$LA/$PREFIX.jarvis.plist" 2>/dev/null || true
    launchctl load "$LA/$PREFIX.jarvis.plist" 2>/dev/null && echo "  installed: jarvis (hands-free wake word)"
    echo "  If it can't hear you: grant Microphone to the daemon, or use the push-to-talk hotkey."
    ;;
  install-voicebox)
    # Run Voicebox's bundled backend HEADLESS (no GUI needed for TTS). We drop the
    # --parent-pid the GUI passes, so the server keeps running on its own.
    SRV="/Applications/Voicebox.app/Contents/MacOS/voicebox-server"
    [ -x "$SRV" ] || { echo "Voicebox not installed at $SRV"; exit 1; }
    cat > "$LA/$PREFIX.voicebox.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.voicebox</string>
  <key>ProgramArguments</key>
  <array>
    <string>$SRV</string>
    <string>--data-dir</string><string>$HOME/Library/Application Support/sh.voicebox.app</string>
    <string>--port</string><string>17493</string>
  </array>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$R/tasks/logs/voicebox.log</string>
  <key>StandardErrorPath</key><string>$R/tasks/logs/voicebox.err</string>
</dict>
</plist>
EOF
    launchctl unload "$LA/$PREFIX.voicebox.plist" 2>/dev/null || true
    # kill any GUI-spawned server (has --parent-pid) or orphan holding the port, so the
    # daemon can bind instead of crash-looping on EADDRINUSE
    pkill -f 'voicebox-server .*--parent-pid' 2>/dev/null || true
    old=$(lsof -tnP -iTCP:17493 -sTCP:LISTEN 2>/dev/null | head -1)
    [ -n "$old" ] && kill "$old" 2>/dev/null && sleep 2
    launchctl load "$LA/$PREFIX.voicebox.plist" 2>/dev/null && echo "  installed: voicebox (headless TTS server on :17493)"
    echo "  Quit the Voicebox GUI if it's open (it would fight for the port)."
    ;;
  remove)
    for n in brief digest sync watch tidy evolve scout groom learn jarvis voicebox ccr; do
      p="$LA/$PREFIX.$n.plist"
      # || true: under set -e a plist that exists but isn't loaded must not abort the loop
      [ -e "$p" ] && { launchctl unload "$p" 2>/dev/null || true; }
      rm -f "$p" && echo "  removed: $n"
    done
    ;;
  *) echo "usage: nb schedule [install|install-jarvis|install-voicebox|status|remove]"; exit 1 ;;
esac
