#!/usr/bin/env bash
# setup-fallback.sh — install|status|remove the "never run out" local brain.
#
# Stack: Ollama only. Its native Anthropic-format API (/v1/messages on :11434)
# lets bin/claudew retry any claude invocation against a local model when
# subscription usage caps — ToS-safe, $0, fully local. The local model is a
# brownout brain: keeps Jarvis talking and simple tasks moving; heavy work
# waits for the Claude reset.
#
#   bash scripts/setup-fallback.sh install    one-time (brew + ~5GB model pull)
#   bash scripts/setup-fallback.sh status     doctor lines for every component
#   bash scripts/setup-fallback.sh remove     stop the service (keeps downloads)
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${NB_OLLAMA_PORT:-11434}"
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin"

model_for_ram() {
  local gib=$(( $(sysctl -n hw.memsize) / 1073741824 ))
  if [ "$gib" -ge 32 ]; then echo "${NB_OLLAMA_MODEL:-qwen3:14b}"; else echo "${NB_OLLAMA_MODEL:-qwen3:8b}"; fi
}

_up() { curl -s --connect-timeout 1 --max-time 1 -o /dev/null "$1" 2>/dev/null; }

case "${1:-status}" in
  install)
    command -v brew >/dev/null 2>&1 || { echo "Homebrew required (brew.sh)"; exit 1; }
    MODEL=$(model_for_ram)
    echo "Installing local fallback brain (model: $MODEL)..."
    command -v ollama >/dev/null 2>&1 || brew install ollama
    brew services start ollama >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do _up "http://127.0.0.1:$PORT" && break; sleep 1; done
    ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL" || ollama pull "$MODEL"
    echo
    "$0" status
    ;;

  status)
    MODEL=$(model_for_ram)
    if command -v ollama >/dev/null 2>&1; then
      if _up "http://127.0.0.1:$PORT"; then o="up on :$PORT"; else o="installed, not running (brew services start ollama)"; fi
    else o="NOT INSTALLED"; fi
    printf "  %-14s %s\n" "ollama:" "$o"
    if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then m="$MODEL pulled"; else m="$MODEL NOT PULLED"; fi
    printf "  %-14s %s\n" "model:" "$m"
    # the exact endpoint claudew will hit (first call after idle loads the
    # model into RAM, so give it time)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 45 -X POST "http://127.0.0.1:$PORT/v1/messages" \
      -H 'content-type: application/json' -H 'x-api-key: x' \
      -d "{\"model\":\"$MODEL\",\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\".\"}]}" 2>/dev/null)
    printf "  %-14s %s\n" "anthropic api:" "$([ "$code" = "200" ] && echo "/v1/messages OK" || echo "unreachable (HTTP ${code:-000})")"
    last=$(grep '"cmd":"claude-fallback"' "$R/tasks/.telemetry.jsonl" 2>/dev/null | tail -1 | sed 's/.*"ts":"\([^"]*\)".*/\1/')
    printf "  %-14s %s\n" "last brownout:" "${last:-never}"
    ;;

  remove)
    brew services stop ollama >/dev/null 2>&1 || true
    echo "  ollama service stopped (binary and model stay installed)"
    ;;

  *) echo "usage: setup-fallback.sh [install|status|remove]"; exit 1 ;;
esac
