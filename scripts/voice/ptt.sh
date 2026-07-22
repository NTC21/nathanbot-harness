#!/usr/bin/env bash
# ptt.sh — push-to-talk for nathanbot voice. One voice turn, NO wake word needed
# (works even without a Picovoice key). Bound to a global hotkey via skhd
# (ctrl+alt - j). Reliable fallback when it's noisy or the wake word misfires.
set -uo pipefail
R="$(cd "$(dirname "$0")/../.." && pwd)"
exec "$R/bin/nb" jarvis once
