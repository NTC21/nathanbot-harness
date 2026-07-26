#!/usr/bin/env python3
"""PreToolUse guard for the file tools (Read/Write/Edit/Grep/Glob/NotebookEdit).

Reads the hook payload as JSON on STDIN. The previous version of these hooks read
$CLAUDE_TOOL_INPUT, which does not exist, so every check silently passed — the
guard had never blocked anything. Fails CLOSED: if the payload cannot be parsed,
the tool call is denied and the reason is printed, because a guard that cannot
see its input cannot approve anything. Loud beats silent.

exit 0 = allow, exit 2 = deny (stderr goes back to the model).
"""
import sys
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nb_guard import check  # noqa: E402

# tool -> (field holding the path, is this a write?)
FIELDS = {
    "Read":         ("file_path", False),
    "Grep":         ("path",      False),
    "Glob":         ("path",      False),
    "Write":        ("file_path", True),
    "Edit":         ("file_path", True),
    "NotebookEdit": ("notebook_path", True),
}


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        # Not invoked as a hook (manual run / smoke test): nothing to judge.
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        print("BLOCKED — path guard could not parse its hook payload, so it is "
              "failing closed. Inspect ~/.claude/hooks/guard-paths.py.", file=sys.stderr)
        return 2

    tool = payload.get("tool_name", "")
    tin = payload.get("tool_input") or {}
    if tool not in FIELDS:
        return 0

    field, is_write = FIELDS[tool]
    path = tin.get(field, "")
    if not path:
        return 0

    reason = check(path, write=is_write)
    if reason:
        print(f"BLOCKED by nathanbot path guard — {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
