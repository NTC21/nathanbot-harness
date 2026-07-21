#!/usr/bin/env bash
# build-ui.sh — compile the React UI into ui/dist that the server serves.
set -euo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
cd "$R/ui-app"
[ -d node_modules ] || npm install
npm run build
echo "built → ui/dist  ·  restart server: launchctl kickstart -k gui/$(id -u)/com.nathanbot.ui"
