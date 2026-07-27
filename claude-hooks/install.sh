#!/usr/bin/env bash
# install.sh — link nathanbot's Claude Code guards into ~/.claude/hooks/.
#
# The guards are PreToolUse hooks that stop an agent reading credentials or
# writing anything that would let it widen its own permissions. They live here
# (tracked) and are symlinked into place, so editing the tracked file takes
# effect immediately and a fresh machine is one command away.
#
# It also wires them into ~/.claude/settings.json, preserving any hooks already
# configured there.
#
#   bash claude-hooks/install.sh
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="$HOME/.claude/hooks"
SETTINGS="$HOME/.claude/settings.json"

mkdir -p "$DST"
for f in nb_guard.py guard-paths.py guard-bash.py guard-canary.py; do
  chmod +x "$SRC/$f" 2>/dev/null || true
  ln -sf "$SRC/$f" "$DST/$f"
  echo "  linked $f"
done

# per-machine extras: seeded once, then never overwritten (it is not tracked)
if [ ! -f "$DST/deny-local.txt" ]; then
  cp "$SRC/deny-local.example.txt" "$DST/deny-local.txt"
  echo "  seeded deny-local.txt — add this machine's credential dirs to it"
fi

python3 - "$SETTINGS" "$DST" <<'PY'
import json, os, sys, collections
settings, hooks_dir = sys.argv[1], sys.argv[2]
try:
    with open(settings) as f:
        d = json.load(f, object_pairs_hook=collections.OrderedDict)
except (OSError, ValueError):
    d = collections.OrderedDict()

h = d.setdefault("hooks", collections.OrderedDict())
want = [
    ("Bash", f"python3 {hooks_dir}/guard-bash.py"),
    # mcp__.* too: the FIELDS map in guard-paths.py is a closed enumeration and
    # fails open, so an MCP server that takes a local path (Word, PowerPoint,
    # the browser file_upload tools) was never screened at all.
    ("Read|Write|Edit|Grep|Glob|NotebookEdit|mcp__.*", f"python3 {hooks_dir}/guard-paths.py"),
]
pre = [g for g in h.get("PreToolUse", [])
       if not any("guard-bash.py" in x.get("command", "") or "guard-paths.py" in x.get("command", "")
                  for x in g.get("hooks", []))]
for matcher, cmd in want:
    pre.append({"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]})
h["PreToolUse"] = pre

# canary: proves at session start that the guard is actually live. The hooks this
# replaced failed silently for their whole existence, so "it is installed" and
# "it is working" must be separately observable.
canary = {"type": "command", "command": f"python3 {hooks_dir}/guard-canary.py", "timeout": 10}
ss = h.setdefault("SessionStart", [])
for g in ss:
    g["hooks"] = [x for x in g.get("hooks", []) if "guard-canary.py" not in x.get("command", "")]
if ss:
    ss[0].setdefault("hooks", []).append(canary)
else:
    ss.append({"hooks": [canary]})

with open(settings, "w") as f:
    json.dump(d, f, indent=2)
print("  wired into ~/.claude/settings.json")
PY

echo "guards installed — new sessions pick them up; the canary warns if they ever stop blocking"
