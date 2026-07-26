#!/usr/bin/env bash
# Install nathanbot's git hooks. .git/hooks is not version-controlled, so the
# real copies live in scripts/hooks/ and this symlinks them into place — that way
# an edit to the tracked file takes effect without a re-install, and a fresh
# clone gets them with one command.
set -euo pipefail
R="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$R"

for h in pre-commit; do
  src="$R/scripts/hooks/$h"
  dst="$R/.git/hooks/$h"
  [ -f "$src" ] || continue
  chmod +x "$src"
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    mv "$dst" "$dst.bak"
    echo "  existing $h backed up to $h.bak"
  fi
  ln -sf "$src" "$dst"
  echo "  installed $h"
done
echo "git hooks installed"
