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


def _strings(obj, depth=0):
    """Every string in a nested tool_input, so an unknown tool's path argument is
    found wherever its schema happens to put it."""
    if depth > 6:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v, depth + 1)


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
        # FIELDS is a closed enumeration, so anything not named fails OPEN. That is
        # fine for tools with no filesystem reach and wrong for the ones that have
        # it — MCP servers for Word, PowerPoint and the browsers all take local
        # paths and none of them are in this list, nor could they be: the set
        # depends on which servers are connected.
        #
        # So for unknown tools, screen every path-shaped string in the arguments
        # against the credential tier. Read semantics only (write=False): DENY_ALL
        # is denied in both directions, which is the part worth protecting, and
        # guessing write on an unknown schema would fence off ordinary work.
        for val in _strings(tin):
            if "/" not in val and not val.startswith("~"):
                continue
            reason = check(val, write=False)
            if reason:
                print(f"BLOCKED by nathanbot path guard — {tool} argument "
                      f"'{val}': {reason}", file=sys.stderr)
                return 2
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
