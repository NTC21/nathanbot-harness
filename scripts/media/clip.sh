#!/usr/bin/env bash
# clip.sh src=in.mp4 in=00:00:05 out=00:00:20 dst=clip.mp4
# stream-copy cut (fast, no re-encode). Use transcode.sh if you need frame-accurate.
set -euo pipefail
for kv in "$@"; do declare "${kv%%=*}=${kv#*=}"; done
: "${src:?need src=}" "${in:?need in=}" "${out:?need out=}" "${dst:?need dst=}"
ffmpeg -ss "$in" -to "$out" -i "$src" -c copy "$dst"
echo "wrote $dst"
