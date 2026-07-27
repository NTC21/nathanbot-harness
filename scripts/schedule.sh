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
# The 22:45 sync job commits+pushes THIS repo. Nothing pushes project code or merges. Execution (`nb run`) stays manual
# until you explicitly add it.
set -euo pipefail

R="$(cd "$(dirname "$0")/.." && pwd)"
NB="$R/bin/nb"
LA="$HOME/Library/LaunchAgents"
PREFIX="com.nathanbot"
mkdir -p "$LA" "$R/tasks/logs"

# mkjob <name> <hour> <minute> <extra-plist-keys> <nb args> [weekday] [day]
#
# Every calendar job gets RunAtLoad=true and runs through rundue.sh. launchd
# replays a missed StartCalendarInterval across sleep but NOT across a
# power-off, so without this a job whose time passed while the Mac was off is
# simply skipped forever. rundue.sh turns the boot-time firing into a catch-up
# when the window was missed, and a no-op when it wasn't. Pass weekday/day so
# the guard knows the real cadence (they must match $extra).
# A job is paused by renaming its plist to <label>.plist.paused. `install` must
# respect that — it used to happily recreate and load paused jobs, silently
# turning them back on.
paused() { [ -e "$LA/$PREFIX.$1.plist.paused" ]; }

mkjob() {
  local name="$1" hour="$2" minute="$3" extra="$4" args="$5"
  local weekday="${6:--}" day="${7:--}"
  local plist="$LA/$PREFIX.$name.plist"
  if paused "$name"; then echo "  skipped (paused): $name"; return 0; fi
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
    <string>$R/scripts/rundue.sh $name $hour $minute $weekday $day -- $NB $args</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$hour</integer>
    <key>Minute</key><integer>$minute</integer>
$extra
  </dict>
  <key>StandardOutPath</key><string>$R/tasks/logs/$name.log</string>
  <key>StandardErrorPath</key><string>$R/tasks/logs/$name.err</string>
  <key>RunAtLoad</key><true/>
  <key>AbandonProcessGroup</key><true/>
</dict>
</plist>
EOF
  # Seed the stamp on first install only. Without it, RunAtLoad would treat the
  # most recent past occurrence as missed and fire every job the moment you
  # install — a burst of briefs/digests nobody asked for. Re-installing an
  # already-scheduled job leaves its real stamp alone.
  mkdir -p "$R/tasks/state"
  if [ ! -f "$R/tasks/state/$name.last" ]; then
    python3 "$R/scripts/lastdue.py" --hour "$hour" --minute "$minute" \
      --weekday "$weekday" --day "$day" > "$R/tasks/state/$name.last" 2>/dev/null || true
    # lastdue exits 1 when no occurrence has happened yet; don't leave an empty
    # stamp behind, or the guard reads it as "never run" and can't reseed
    [ -s "$R/tasks/state/$name.last" ] || rm -f "$R/tasks/state/$name.last"
  fi
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist" 2>/dev/null && echo "  installed: $name"
}

case "${1:-install}" in
  install)
    echo "Installing nathanbot scheduled jobs..."
    mkjob brief  7  30 ""                              "brief --quiet --deliver --speak"
    mkjob digest 22  0 ""                              "digest"
    mkjob sync   22 45 ""                              "sync"
    mkjob tidy   9   0 "    <key>Weekday</key><integer>0</integer>" "tidy"          0
    mkjob evolve 8   0 "    <key>Weekday</key><integer>1</integer>" "evolve --apply" 1
    mkjob groom  9  30 "    <key>Weekday</key><integer>0</integer>" "groom --apply"  0
    mkjob learn  8  30 "    <key>Weekday</key><integer>1</integer>" "learn --apply"  1
    mkjob scout  8  30 "    <key>Day</key><integer>1</integer>"     "scout"          - 1
    # watcher runs on a 2-hour interval (not a clock time); watch.sh self-mutes 23:00–07:00.
    # Deliberately slow: the owner finds frequent ambient pings annoying.
    if paused watch; then echo "  skipped (paused): watch"; else
    cat > "$LA/$PREFIX.watch.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.watch</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>-lc</string><string>$NB watch</string></array>
  <key>StartInterval</key><integer>7200</integer>
  <key>StandardOutPath</key><string>$R/tasks/logs/watch.log</string>
  <key>StandardErrorPath</key><string>$R/tasks/logs/watch.err</string>
  <key>RunAtLoad</key><false/>
  <key>AbandonProcessGroup</key><true/>
</dict>
</plist>
EOF
    launchctl unload "$LA/$PREFIX.watch.plist" 2>/dev/null || true
    launchctl load "$LA/$PREFIX.watch.plist" 2>/dev/null && echo "  installed: watch"
    fi
    echo
    echo "Done. nathanbot now runs on its own:"
    echo "  brief   daily 07:30      (notification + tasks/.brief-*.md)"
    echo "  digest  daily 22:00      (daily notes -> tasks + wiki facts)"
    echo "  watch   every 2 hours    (ambient: meetings, stale repos, VIP mail)"
    echo "  tidy    Sundays 09:00    (report only)"
    echo "  evolve  Mondays 08:00    (--apply: auto-fixes the safe tier, then proposes)"
    echo "  learn   Mondays 08:30    (--apply: model-of-the owner edits from explicit feedback)"
    echo "  groom   Sundays 09:30    (--apply: archives stale tasks)"
    echo "  sync    daily 22:45      (commit + push THIS repo)"
    echo "  scout   1st of month     (new tools -> wiki pages)"
    echo
    echo "  This list is hand-maintained and drifts. 'nb schedule status' is the truth."
    echo
    echo "The 22:45 sync job commits+pushes THIS repo; nothing pushes project code or merges. 'nb run' stays manual."
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
  install-telegram)
    # The two-way phone channel. Long-polls Telegram (KeepAlive), routes your texts
    # to the operator, texts replies back. Needs ~/.secrets/telegram/{bot_token,chat_id}.
    [ -f "$HOME/.secrets/telegram/bot_token" ] || { echo "no ~/.secrets/telegram/bot_token — create a bot via @BotFather first"; exit 1; }
    [ -f "$HOME/.secrets/telegram/chat_id" ]   || { echo "no ~/.secrets/telegram/chat_id — run: nb tg --whoami"; exit 1; }
    cat > "$LA/$PREFIX.telegram.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.telegram</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>-lc</string><string>$NB telegram</string></array>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$R/tasks/logs/telegram.log</string>
  <key>StandardErrorPath</key><string>$R/tasks/logs/telegram.err</string>
</dict>
</plist>
EOF
    launchctl unload "$LA/$PREFIX.telegram.plist" 2>/dev/null || true
    launchctl load "$LA/$PREFIX.telegram.plist" 2>/dev/null && echo "  installed: telegram (two-way phone bridge)"
    ;;
  install-news)
    # Daily tech/AI news brief pushed to your phone at 8:00.
    mkjob news 8 0 "" "news --deliver"
    ;;
  install-nudge)
    # Proactive calendar heads-ups. Runs every 10 min; nudge.py dedups + is silent
    # when nothing's imminent, so a frequent interval is cheap.
    cat > "$LA/$PREFIX.nudge.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.nudge</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>-lc</string><string>python3 $R/scripts/proactive/nudge.py</string></array>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$R/tasks/logs/nudge.log</string>
  <key>StandardErrorPath</key><string>$R/tasks/logs/nudge.err</string>
</dict>
</plist>
EOF
    launchctl unload "$LA/$PREFIX.nudge.plist" 2>/dev/null || true
    launchctl load "$LA/$PREFIX.nudge.plist" 2>/dev/null && echo "  installed: nudge (proactive calendar heads-ups every 10m)"
    ;;
  install-activity)
    # RETIRED 2026-07-26. This job pinged every 30 min about new commits across
    # your repos — i.e. it was reporting your own work back to you. Removed as
    # notification noise. `nb schedule remove` still cleans up any stale plist.
    echo "  activity is retired (it only reported your own commits); nothing installed"
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
    # server and skhd are installed by hand (no generator in this repo), so they
    # survived `remove` and kept running. ccr dropped — nothing ever installed it.
    for n in brief digest sync watch tidy evolve scout groom learn jarvis voicebox \
             telegram nudge activity news server skhd; do
      p="$LA/$PREFIX.$n.plist"
      # || true: under set -e a plist that exists but isn't loaded must not abort the loop
      [ -e "$p" ] && { launchctl unload "$p" 2>/dev/null || true; }
      rm -f "$p" && echo "  removed: $n"
    done
    ;;
  *) echo "usage: nb schedule [install|install-jarvis|install-voicebox|install-telegram|install-nudge|install-news|status|remove]"; exit 1 ;;
esac
