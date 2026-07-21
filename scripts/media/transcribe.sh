#!/usr/bin/env bash
# transcribe.sh src=in.mp4  -> writes in.srt next to source
# requires: whisper (brew install openai-whisper). Stub until installed.
set -euo pipefail
for kv in "$@"; do declare "${kv%%=*}=${kv#*=}"; done
: "${src:?need src=}"
if ! command -v whisper >/dev/null 2>&1; then
  echo "whisper not installed. run: brew install openai-whisper" >&2; exit 1
fi
whisper "$src" --model small --output_format srt --output_dir "$(dirname "$src")"
