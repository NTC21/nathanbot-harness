#!/usr/bin/env bash
# source this to load secrets + env into the shell
set -a
[ -f "$HOME/.secrets/ai-hub.env" ] && . "$HOME/.secrets/ai-hub.env"
[ -f "$(dirname "$0")/../.env" ] && . "$(dirname "$0")/../.env"
set +a
