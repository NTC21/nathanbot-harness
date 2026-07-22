#!/usr/bin/env bash
# source this to load secrets + env into the shell
set -a
[ -f "$HOME/.secrets/ai-hub.env" ] && . "$HOME/.secrets/ai-hub.env"
# BASH_SOURCE, not $0 — this file is SOURCED, so $0 is the caller's path
[ -f "$(dirname "${BASH_SOURCE[0]}")/../.env" ] && . "$(dirname "${BASH_SOURCE[0]}")/../.env"
set +a
