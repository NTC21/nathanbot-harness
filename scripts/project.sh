#!/usr/bin/env bash
# project.sh — onboard a project into nathanbot so it knows about it everywhere.
#
#   nb project new <name> [--type next|expo|node|python|static] [--caps a,b,c] [--autonomy lvl]
#   nb project add <path> [--caps a,b,c] [--autonomy lvl]   register an EXISTING project
#   nb project list                                          what's registered
#
# Does all of it in one shot:
#   1. scaffolds (new only) — git, gitignore, CLAUDE.md, .env.example, .nvmrc
#   2. registers in config/projects.json  (autonomy: how much AI can do unattended)
#   3. registers in config/profiles.json  (capability layers -> skills/plugins/guidance)
#   4. runs `nb profile sync` so .claude/ config is generated
#   5. creates a wiki page so it's in the knowledge graph
#   6. captures a first task so it shows up in the queue
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
PROJECTS="$HOME/Projects"
B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; X=$'\033[0m'

CMD="${1:-list}"; shift || true
NAME=""; TYPE="node"; CAPS=""; AUTO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE="$2"; shift 2 ;;
    --caps) CAPS="$2"; shift 2 ;;
    --autonomy) AUTO="$2"; shift 2 ;;
    *) NAME="$1"; shift ;;
  esac
done

suggest_caps() {
  case "$1" in
    next)   echo "typescript,nextjs,react,tailwind,ui-design" ;;
    expo)   echo "typescript,expo,react,ui-design" ;;
    python) echo "python" ;;
    static) echo "ui-design,tailwind" ;;
    *)      echo "typescript" ;;
  esac
}

register() {
  local rel="$1" caps="$2" auto="$3" domain="$4"
  python3 - "$R" "$rel" "$caps" "$auto" "$domain" <<'PY'
import json, sys
R, rel, caps, auto, domain = sys.argv[1:6]
caplist = [c.strip() for c in caps.split(",") if c.strip()]

pf = f"{R}/config/profiles.json"
d = json.load(open(pf))
d["paths"][rel] = {"capabilities": caplist}
json.dump(d, open(pf, "w"), indent=2)

pj = f"{R}/config/projects.json"
d = json.load(open(pj))
key = rel.split("/")[-1].lower().replace("_", "-")
d["projects"][key] = {
    "path": "${CODE_ROOT}/" + rel,
    "domain": domain,
    "autonomy": auto,
}
json.dump(d, open(pj, "w"), indent=2)
print(f"  registered as '{key}'  autonomy={auto}  caps={', '.join(caplist) or 'none'}")
PY
}

wiki_page() {
  local key="$1" rel="$2" caps="$3"
  local f="$R/wiki/pages/$key.md"
  [ -f "$f" ] && { printf "  %swiki page exists, left alone%s\n" "$D" "$X"; return; }
  cat > "$f" <<EOF
---
title: $key
type: project
status: active
updated: $(date +%Y-%m-%d)
---

<one-line: what this is and who it's for>

## Current state
Created $(date +%Y-%m-%d). Lives at \`~/Projects/$rel\`.
Capabilities: ${caps:-none}

## Decisions
- (none yet)

## Links
[[owner]] · [[index]]
EOF
  grep -q "\[\[$key\]\]" "$R/wiki/index.md" || \
    printf -- "- [[%s]] — new project\n" "$key" >> "$R/wiki/index.md"
  printf -- "\n## %s\n- created project page [[%s]]\n" "$(date +%Y-%m-%d)" "$key" >> "$R/wiki/log.md"
  printf "  %s✓%s wiki page + index entry\n" "$G" "$X"
}

case "$CMD" in
  new)
    [ -n "$NAME" ] || { echo "usage: nb project new <name> [--type ...]"; exit 1; }
    [ -e "$PROJECTS/$NAME" ] && { echo "error: $PROJECTS/$NAME exists (use 'nb project add')"; exit 1; }
    [ -z "$CAPS" ] && CAPS="$(suggest_caps "$TYPE")"
    [ -z "$AUTO" ] && AUTO="auto-merge"
    printf "%sCreating %s%s\n" "$B" "$NAME" "$X"
    "$R/scripts/new-project.sh" "$NAME" --type "$TYPE" >/dev/null
    printf "  %s✓%s scaffolded (git, gitignore, CLAUDE.md, .env.example)\n" "$G" "$X"
    register "$NAME" "$CAPS" "$AUTO" "coding"
    "$R/scripts/profile.sh" apply "$NAME" >/dev/null 2>&1
    printf "  %s✓%s capability config generated (.claude/)\n" "$G" "$X"
    wiki_page "$(echo "$NAME" | tr 'A-Z' 'a-z')" "$NAME" "$CAPS"
    "$R/bin/nb" add "flesh out $NAME — set the one-liner in its wiki page and CLAUDE.md" >/dev/null
    printf "  %s✓%s first task captured\n" "$G" "$X"
    printf "\n%sready:%s cd ~/Projects/%s\n" "$B" "$X" "$NAME"
    ;;

  add)
    [ -n "$NAME" ] || { echo "usage: nb project add <path-relative-to-~/Projects>"; exit 1; }
    NAME="${NAME#$PROJECTS/}"; NAME="${NAME%/}"
    [ -d "$PROJECTS/$NAME" ] || { echo "error: $PROJECTS/$NAME not found"; exit 1; }
    if [ -z "$CAPS" ]; then
      # guess from what's actually in the repo
      c="typescript"
      [ -f "$PROJECTS/$NAME/package.json" ] && grep -q '"next"' "$PROJECTS/$NAME/package.json" 2>/dev/null && c="$c,nextjs,react,tailwind,ui-design"
      [ -f "$PROJECTS/$NAME/app.json" ] && c="typescript,expo,react,ui-design"
      [ -f "$PROJECTS/$NAME/pyproject.toml" ] || [ -f "$PROJECTS/$NAME/requirements.txt" ] && c="python"
      [ -f "$PROJECTS/$NAME/platformio.ini" ] && c="embedded-c"
      CAPS="$c"
      printf "  %sdetected capabilities: %s%s\n" "$D" "$CAPS" "$X"
    fi
    [ -z "$AUTO" ] && AUTO="auto-pr"
    printf "%sRegistering %s%s\n" "$B" "$NAME" "$X"
    register "$NAME" "$CAPS" "$AUTO" "coding"
    "$R/scripts/profile.sh" apply "$NAME" >/dev/null 2>&1
    printf "  %s✓%s capability config generated\n" "$G" "$X"
    wiki_page "$(basename "$NAME" | tr 'A-Z' 'a-z')" "$NAME" "$CAPS"
    ;;

  list)
    python3 - "$R" <<'PY'
import json, sys, os
R = sys.argv[1]
pj = json.load(open(f"{R}/config/projects.json"))["projects"]
pf = json.load(open(f"{R}/config/profiles.json"))["paths"]
print("\033[1mRegistered projects\033[0m\n")
for k, v in sorted(pj.items()):
    rel = v["path"].replace("${CODE_ROOT}/", "")
    caps = pf.get(rel, {}).get("capabilities", [])
    a = v.get("autonomy", "?")
    col = {"auto-merge": "\033[32m", "auto-pr": "\033[33m", "review-required": "\033[31m"}.get(a, "")
    print(f"  {k:<20} {col}{a:<16}\033[0m \033[2m{', '.join(caps) or 'no capabilities'}\033[0m")
PY
    ;;
  *) echo "usage: nb project [new|add|list]"; exit 1 ;;
esac
