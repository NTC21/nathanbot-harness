#!/usr/bin/env bash
# Global thought-capture. Pops a dialog anywhere, files whatever you type via `nb add`
# (which auto-triages it into a real task in the background).
#
# Bind to a hotkey (one-time, ~30s): Raycast/Hammerspoon script command, OR
# System Settings ▸ Keyboard ▸ Keyboard Shortcuts ▸ Services / a macOS Shortcut
# that runs:  $HOME/Projects/nathanbot/scripts/capture.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

txt=$(osascript -e 'set t to text returned of (display dialog "Capture a thought:" default answer "" with title "nathanbot" buttons {"Cancel","Capture"} default button "Capture")' 2>/dev/null) || exit 0
[ -z "${txt// }" ] && exit 0

"$ROOT/bin/nb" add "$txt" >/dev/null 2>&1
osascript -e "display notification \"$txt\" with title \"nathanbot\" subtitle \"captured\"" >/dev/null 2>&1 || true
