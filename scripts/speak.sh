#!/usr/bin/env bash
# speak.sh — nathanbot's voice. Uses the best backend available, in order:
#   0. Fish Audio  if ~/.secrets/fishaudio/api_key exists     (cloud, best British Jarvis)
#   1. edge-tts    if the binary is installed                 (cloud, free, no account)
#   2. Voicebox    if its local server is up (local neural TTS — instant & private)
#   3. ElevenLabs  if ~/.secrets/elevenlabs/api_key exists    (cloud, paid)
#   4. OpenAI TTS  if ~/.secrets/openai/api_key exists        (cloud, cheap)
#   5. macOS `say` with the best installed voice              (free, offline fallback)
#
#   nb speak "text"   |   echo text | nb speak
# NB_VOICE            = a `say` voice name OR an ElevenLabs/OpenAI voice id.
# NB_VOICEBOX_PROFILE = a Voicebox voice-profile name (e.g. "Jarvis").
# NB_FISH_MODEL       = Fish Audio model header  (default s2.1-pro-free)
# NB_FISH_VOICE       = Fish Audio reference_id  (default: British "J.A.R.V.I.S" library voice)
# NB_EDGE_VOICE       = edge-tts voice           (default en-GB-RyanNeural)
set -uo pipefail
txt="$*"
[ -z "$txt" ] && [ ! -t 0 ] && txt="$(cat)"
[ -z "${txt// }" ] && exit 0
SEC="$HOME/.secrets"
VB="http://127.0.0.1:17493"
_json() { printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'; }

# make any text listenable: strip markdown/symbols, humanize IDs, cap length at a
# sentence boundary (NB_SPEAK_MAX chars, default 600; 0 = unlimited)
txt="$(python3 - "$txt" <<'PY'
import os, re, sys
t = sys.argv[1]
t = re.sub(r'```.*?```', ' code omitted. ', t, flags=re.S)      # fenced code
t = re.sub(r'`([^`]*)`', r'\1', t)                              # inline code
t = re.sub(r'\*\*([^*]+)\*\*', r'\1', t)
t = re.sub(r'\*([^*]+)\*', r'\1', t)
t = re.sub(r'^#{1,6}\s*', '', t, flags=re.M)                    # headings
t = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', t)                  # links -> text
t = re.sub(r'^\s*[-*•·]\s+', '', t, flags=re.M)                 # bullets
t = t.replace('→', ' to ').replace('←', ' from ').replace('·', ', ')
t = re.sub(r'\bt-0*(\d+)\b', r'task \1', t)                     # t-0003 -> task 3
t = re.sub(r'[_#>|~]', ' ', t)
t = re.sub(r'\s+', ' ', t).strip()
cap = int(os.environ.get('NB_SPEAK_MAX', '600') or 0)
if cap and len(t) > cap:
    cut = t[:cap]
    m = max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '))
    t = cut[:m+1] if m > 40 else cut
print(t)
PY
)"
[ -z "${txt// }" ] && exit 0

# resolve edge-tts even under launchd's bare PATH
EDGE="${NB_EDGE_TTS_BIN:-$(command -v edge-tts || true)}"
[ -x "${EDGE:-/nonexistent}" ] || { [ -x "$HOME/.local/bin/edge-tts" ] && EDGE="$HOME/.local/bin/edge-tts" || EDGE=""; }

# ── online gate: one cheap probe so an offline Mac never eats cloud timeouts ──
NET_OK=""
if [ -f "$SEC/fishaudio/api_key" ] || [ -n "$EDGE" ]; then
  # no -f: any HTTP response (even 404) proves the network is up
  curl -s --connect-timeout 1 --max-time 2 -o /dev/null https://api.fish.audio 2>/dev/null && NET_OK=1
fi

# ── 0. Fish Audio (cloud — the Jarvis butler voice) ──────────────────────────
if [ -n "$NET_OK" ] && [ -f "$SEC/fishaudio/api_key" ]; then
  key=$(tr -d '[:space:]' < "$SEC/fishaudio/api_key")
  vid="${NB_FISH_VOICE:-c231dcd3116a4c0984e3bced753c1274}"   # British "J.A.R.V.I.S" library voice
  tmp="$(mktemp).mp3"
  # key via --config on stdin, never argv (argv is world-readable in the process list)
  if curl -sf --connect-timeout 3 --max-time 8 -X POST "https://api.fish.audio/v1/tts" \
       --config <(printf 'header = "Authorization: Bearer %s"\n' "$key") \
       -H "Content-Type: application/json" \
       -H "model: ${NB_FISH_MODEL:-s2.1-pro-free}" \
       -d "{\"text\":$(_json "$txt"),\"reference_id\":$(_json "$vid"),\"format\":\"mp3\",\"mp3_bitrate\":128}" \
       -o "$tmp" \
     && [ -s "$tmp" ] && [ "$(head -c1 "$tmp")" != "{" ]; then   # JSON body = API error, not audio
    afplay "$tmp"; rm -f "$tmp"; exit 0
  fi
  rm -f "$tmp"   # fall through
fi

# ── 1. edge-tts (cloud, free, no account — British neural) ───────────────────
if [ -n "$NET_OK" ] && [ -n "$EDGE" ]; then
  tmp="$(mktemp).mp3"
  "$EDGE" --voice "${NB_EDGE_VOICE:-en-GB-RyanNeural}" --text "$txt" --write-media "$tmp" >/dev/null 2>&1 &
  epid=$!
  for _ in $(seq 1 80); do kill -0 "$epid" 2>/dev/null || break; sleep 0.1; done   # ~8s watchdog (no `timeout` on macOS)
  kill "$epid" 2>/dev/null; wait "$epid" 2>/dev/null
  if [ -s "$tmp" ]; then afplay "$tmp"; rm -f "$tmp"; exit 0; fi
  rm -f "$tmp"   # fall through
fi

# ── 2. Voicebox (local neural TTS / cloned voice) — only if the app's server is up ──
if curl -sf -o /dev/null --max-time 1 "$VB/docs" 2>/dev/null; then
  prof="${NB_VOICEBOX_PROFILE:-Jarvis}"   # Jarvis = Kokoro British male (George) by default
  if [ -n "$prof" ]; then
    body="{\"text\":$(_json "$txt"),\"profile\":$(_json "$prof")}"
  else
    body="{\"text\":$(_json "$txt")}"
  fi
  if curl -sf --max-time 30 -X POST "$VB/speak" \
       -H "Content-Type: application/json" -H "X-Voicebox-Client-Id: nathanbot" \
       -d "$body" >/dev/null 2>&1; then
    exit 0                       # Voicebox played it server-side
  fi
  # fall through if it errored
fi

# ── 3. ElevenLabs ────────────────────────────────────────────────────────────
if [ -f "$SEC/elevenlabs/api_key" ]; then
  key=$(tr -d '[:space:]' < "$SEC/elevenlabs/api_key")
  vid="${NB_VOICE:-pNInz6obpgDQGcFmaJgB}"   # 'Adam' — deep, calm; override w/ a voice id
  tmp="$(mktemp).mp3"
  # key via --config on stdin, never argv (argv is world-readable in the process list)
  if curl -sf -X POST "https://api.elevenlabs.io/v1/text-to-speech/$vid" \
       --config <(printf 'header = "xi-api-key: %s"\n' "$key") \
       -H "Content-Type: application/json" \
       -d "{\"text\":$(_json "$txt"),\"model_id\":\"eleven_turbo_v2_5\"}" -o "$tmp"; then
    afplay "$tmp"; rm -f "$tmp"; exit 0
  fi
  rm -f "$tmp"   # fall through to next backend on failure
fi

# ── 4. OpenAI TTS ────────────────────────────────────────────────────────────
if [ -f "$SEC/openai/api_key" ]; then
  key=$(tr -d '[:space:]' < "$SEC/openai/api_key")
  tmp="$(mktemp).mp3"
  if curl -sf https://api.openai.com/v1/audio/speech \
       --config <(printf 'header = "Authorization: Bearer %s"\n' "$key") \
       -H "Content-Type: application/json" \
       -d "{\"model\":\"tts-1\",\"voice\":\"${NB_VOICE:-onyx}\",\"input\":$(_json "$txt")}" -o "$tmp"; then
    afplay "$tmp"; rm -f "$tmp"; exit 0
  fi
  rm -f "$tmp"
fi

# ── 5. macOS say — pick the best voice actually installed ────────────────────
command -v say >/dev/null 2>&1 || { echo "no TTS backend available" >&2; exit 1; }
voice="${NB_VOICE:-}"
if [ -z "$voice" ]; then
  while IFS= read -r v; do
    if say -v '?' 2>/dev/null | grep -qF "$v"; then voice="$v"; break; fi
  done <<'VOICES'
Ava (Premium)
Zoe (Premium)
Serena (Premium)
Evan (Enhanced)
Tom (Enhanced)
Daniel
VOICES
fi
say -v "${voice:-Samantha}" -r "${NB_RATE:-178}" "$txt" 2>/dev/null || say "$txt"
