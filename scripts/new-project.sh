#!/usr/bin/env bash
# new-project.sh — scaffold a new project with the standard layout
#
#   new-project.sh <name> [--type next|expo|node|python|static] [--workspace <dir>]
#
# Creates a project that starts clean: git initialized, gitignore correct,
# CLAUDE.md present, secrets pattern in place, node version pinned.
set -euo pipefail

NAME=""; TYPE="node"; WS="$HOME/Projects"
while [ $# -gt 0 ]; do
  case "$1" in
    --type)      TYPE="$2"; shift 2 ;;
    --workspace) WS="$2";   shift 2 ;;
    -h|--help)   sed -n '2,9p' "$0"; exit 0 ;;
    *)           NAME="$1"; shift ;;
  esac
done
[ -n "$NAME" ] || { echo "usage: new-project.sh <name> [--type next|expo|node|python|static]" >&2; exit 1; }

DIR="$WS/$NAME"
[ -e "$DIR" ] && { echo "error: $DIR already exists" >&2; exit 1; }
mkdir -p "$DIR"
cd "$DIR"

# --- node version pin (matches your installed default) ---
case "$TYPE" in
  python) : ;;
  *) echo "22" > .nvmrc ;;
esac

# --- gitignore: secrets first, always ---
cat > .gitignore <<'EOF'
# secrets — never commit
.env
.env.local
.env.*.local
*.pem
*.p8
*.p12
AuthKey_*.p8

# deps / build
node_modules/
dist/
build/
.next/
__pycache__/
.venv/

# system
.DS_Store
*.log
EOF

cat > .env.example <<'EOF'
# Key NAMES only — never real values.
# Real secrets live in ~/.secrets/ and are sourced, not committed.
EOF

# --- CLAUDE.md so AI has context from day one ---
cat > CLAUDE.md <<EOF
# $NAME

## What this is
<one-liner: what this project does and who it's for>

## Stack
- type: $TYPE
- node: 22 (see .nvmrc)

## Commands
- install: <cmd>
- dev:     <cmd>
- test:    <cmd>
- deploy:  <cmd>

## Conventions
- Secrets: never in-repo. Real values in \`~/.secrets/\`, names in \`.env.example\`.
- Commit style: conventional commits.

## Context
- Related workspace memory: nathanbot/workspace-coding/MEMORY.md
EOF

cat > README.md <<EOF
# $NAME

<short description>

## Setup
\`\`\`bash
nvm use
cp .env.example .env   # fill from ~/.secrets/
\`\`\`
EOF

git init -q
git add -A
git commit -qm "chore: scaffold $NAME" 2>/dev/null || true

echo "✅ created $DIR"
echo "   type: $TYPE · git initialized · gitignore + CLAUDE.md + .env.example in place"
echo
echo "next:"
echo "   cd $DIR"
case "$TYPE" in
  next)   echo "   npx create-next-app@latest . --ts" ;;
  expo)   echo "   npx create-expo-app@latest ." ;;
  python) echo "   uv init && uv venv" ;;
  static) echo "   (add index.html)" ;;
  *)      echo "   npm init -y" ;;
esac
