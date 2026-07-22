#!/usr/bin/env bash
# detach.sh — run a command fully detached from the caller's process group.
#
#   . "$R/scripts/lib/detach.sh"
#   nb_detach "$R/scripts/speak.sh" "hello"
#
# Why: SwiftBar and launchd kill the whole process group when a menu action or
# scheduled job exits. A plain `cmd &` — even with nohup — keeps the caller's
# PGID, so spoken audio dies mid-sentence. start_new_session=True (setsid)
# gives the child its own session and group, which survives the group kill.

nb_detach() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$@" <<'PY' >/dev/null 2>&1
import subprocess, sys
subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 start_new_session=True)
PY
  else
    ( nohup "$@" >/dev/null 2>&1 & ) 2>/dev/null
  fi
}
