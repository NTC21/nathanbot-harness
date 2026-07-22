#!/usr/bin/env bash
# deliver.sh — push one message to every configured channel. Borrowed from
# OpenJarvis's real "display": deliver into surfaces you already use, not a
# bespoke dashboard. Each channel is opt-in and silent if not configured.
#   • macOS notification   — always
#   • iMessage to self     — set NB_IMESSAGE_TO to your iMessage handle (phone/email)
#   • Discord              — put a webhook URL in ~/.secrets/discord/webhook_url
#   (voice is a separate channel via speak.sh / `nb brief --speak`)
#
#   nb deliver "title" "body"      |     echo body | nb deliver "title"
set -uo pipefail
SEC="$HOME/.secrets"
title="${1:-nathanbot}"; body="${2:-}"
[ -z "$body" ] && [ ! -t 0 ] && body="$(cat)"
[ -z "${body// }" ] && exit 0

# 1. macOS notification (always). env-var passing avoids all AppleScript escaping.
NB_T="$title" NB_B="$(printf '%s' "$body" | tr '\n' ' ')" osascript - >/dev/null 2>&1 <<'OSA' || true
display notification (system attribute "NB_B") with title (system attribute "NB_T")
OSA

# 2. iMessage to self (opt-in)
if [ -n "${NB_IMESSAGE_TO:-}" ]; then
  NB_M="$title
$body" NB_TO="$NB_IMESSAGE_TO" osascript - >/dev/null 2>&1 <<'OSA' || true
tell application "Messages"
  send (system attribute "NB_M") to participant (system attribute "NB_TO") of (1st account whose service type = iMessage)
end tell
OSA
fi

# 3. Discord webhook (opt-in)
if [ -f "$SEC/discord/webhook_url" ]; then
  url=$(tr -d '[:space:]' < "$SEC/discord/webhook_url")
  payload=$(python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1]}))' "**$title**
$body")
  curl -sf -X POST "$url" -H "Content-Type: application/json" -d "$payload" >/dev/null 2>&1 || true
fi
