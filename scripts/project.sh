#!/usr/bin/env bash
# project.sh — onboard a project into nathanbot so it knows about it everywhere.
#
#   nb project new <name> [--type next|expo|node|python|static] [--caps a,b,c] [--autonomy lvl]
#   nb project add <path> [--caps a,b,c] [--autonomy lvl] [--key k]  register an EXISTING project
#   nb project list                                          what's registered
#
# --key overrides the projects.json key, which otherwise comes from the last path
# segment. Needed when two paths share a basename (acme-workspace/landing and
# beta-workspace/landing); without it the second registration is refused.
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
NAME=""; TYPE="node"; CAPS=""; AUTO=""; KEY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE="$2"; shift 2 ;;
    --caps) CAPS="$2"; shift 2 ;;
    --autonomy) AUTO="$2"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
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

# Prints the projects.json key on stdout (and nothing else there), so callers can
# use the SAME key for the wiki page instead of deriving it a third way.
register() {
  local rel="$1" caps="$2" auto="$3" domain="$4" want="$5"
  python3 - "$R" "$rel" "$caps" "$auto" "$domain" "$want" <<'PY'
import json, sys
R, rel, caps, auto, domain, want = sys.argv[1:7]
caplist = [c.strip() for c in caps.split(",") if c.strip()]
key = want or rel.split("/")[-1].lower().replace("_", "-")

pjp, pfp = f"{R}/config/projects.json", f"{R}/config/profiles.json"
pj = json.load(open(pjp))
pf = json.load(open(pfp))

# profiles.json is keyed by the full relative path, projects.json by the last
# segment — so two paths can share a key. Both acme-workspace/landing and
# beta-workspace/landing are already in profiles.json, and this used to be a
# bare assignment: registering the second silently replaced the first one's path,
# domain and autonomy. Refuse instead. No auto-generated suffix, because these
# keys get hand-typed into task frontmatter and accounts.json routing.
prior = pj["projects"].get(key)
if prior is not None and prior.get("path", "").replace("${CODE_ROOT}/", "") != rel:
    sys.exit(
        f"error: projects.json already has the key '{key}', pointing at "
        f"{prior.get('path', '?')}.\n"
        f"       Registering {rel} under it would overwrite that project's path, "
        f"domain and autonomy.\n"
        f"       Pick a distinct key:  nb project add {rel} --key <key>")

# Both files are written only after the check, so a refusal leaves neither
# half-written.
pf["paths"][rel] = {"capabilities": caplist}
pj["projects"][key] = {
    "path": "${CODE_ROOT}/" + rel,
    "domain": domain,
    "autonomy": auto,
}
json.dump(pf, open(pfp, "w"), indent=2)
json.dump(pj, open(pjp, "w"), indent=2)
print(f"  registered as '{key}'  autonomy={auto}  caps={', '.join(caplist) or 'none'}",
      file=sys.stderr)
print(key)
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
    # exit 2 = bad invocation, matching argparse and scripts/wiki.sh. The `error:`
    # lines below stay 1: "that path already exists" is a state problem, not a
    # sentence typed wrong. See scripts/lib/telemetry.py.
    [ -n "$NAME" ] || { echo "usage: nb project new <name> [--type ...]" >&2; exit 2; }
    [ -e "$PROJECTS/$NAME" ] && { echo "error: $PROJECTS/$NAME exists (use 'nb project add')"; exit 1; }
    [ -z "$CAPS" ] && CAPS="$(suggest_caps "$TYPE")"
    [ -z "$AUTO" ] && AUTO="auto-merge"
    printf "%sCreating %s%s\n" "$B" "$NAME" "$X"
    "$R/scripts/new-project.sh" "$NAME" --type "$TYPE" >/dev/null
    printf "  %s✓%s scaffolded (git, gitignore, CLAUDE.md, .env.example)\n" "$G" "$X"
    key="$(register "$NAME" "$CAPS" "$AUTO" "coding" "$KEY")" || exit 1
    "$R/scripts/profile.sh" apply "$NAME" >/dev/null 2>&1
    printf "  %s✓%s capability config generated (.claude/)\n" "$G" "$X"
    wiki_page "$key" "$NAME" "$CAPS"
    "$R/bin/nb" add "flesh out $NAME — set the one-liner in its wiki page and CLAUDE.md" >/dev/null
    printf "  %s✓%s first task captured\n" "$G" "$X"
    printf "\n%sready:%s cd ~/Projects/%s\n" "$B" "$X" "$NAME"
    ;;

  add)
    [ -n "$NAME" ] || { echo "usage: nb project add <path-relative-to-~/Projects> [--key k]" >&2; exit 2; }
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
    key="$(register "$NAME" "$CAPS" "$AUTO" "coding" "$KEY")" || exit 1
    "$R/scripts/profile.sh" apply "$NAME" >/dev/null 2>&1
    printf "  %s✓%s capability config generated\n" "$G" "$X"
    wiki_page "$key" "$NAME" "$CAPS"
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
  *) echo "usage: nb project [new|add|list]" >&2; exit 2 ;;
esac
