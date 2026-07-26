#!/usr/bin/env python3
"""Tests for the Claude Code path guards.

Run:  python3 claude-hooks/test_guards.py

These exist because the hooks these replaced failed silently for their entire
existence — they read an env var that does not exist, so every check passed and
nothing was ever blocked. "Installed" and "actually blocking" are different
claims, and only one of them is worth anything.

The bypass cases are not hypothetical. Each was verified against this machine
before being written down:
  - /System/Volumes/Data/<path> is the SAME FILE as <path> (identical inode) but
    os.path.realpath leaves the two spellings distinct
  - APFS is case-insensitive, so .SSH reaches .ssh, and realpath preserves case
  - a .git/hooks entry is often a symlink to a tracked copy, so canonicalizing
    resolves the dangerous location away while the write still lands there
"""
import json
import os
import subprocess
import sys

HOOKS = os.path.dirname(os.path.abspath(__file__))
H = os.path.expanduser("~")
sys.path.insert(0, HOOKS)


def _run(hook, payload, operator=False):
    env = dict(os.environ)
    env.pop("NB_OPERATOR", None)
    if operator:
        env["NB_OPERATOR"] = "1"
    p = subprocess.run([sys.executable, os.path.join(HOOKS, hook)],
                       input=json.dumps(payload), capture_output=True, text=True, env=env)
    return p.returncode == 2


def f(tool, path, operator=False):
    field = "file_path" if tool in ("Read", "Write", "Edit") else "path"
    return _run("guard-paths.py", {"tool_name": tool, "tool_input": {field: path}}, operator)


def b(cmd, cwd=H, operator=False):
    return _run("guard-bash.py",
                {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}, operator)


CASES = [
    ("CREDENTIALS — denied in every context", None, None),
    ("read a private ssh key",              f("Read", f"{H}/.ssh/id_rsa"), True),
    ("...also for the operator",            f("Read", f"{H}/.ssh/id_rsa", True), True),
    ("firmlink alias spelling",             f("Read", f"/System/Volumes/Data{H}/.ssh/id_rsa"), True),
    ("case-variant spelling",               f("Read", f"{H}/.SSH/id_rsa"), True),
    ("relative traversal",                  f("Read", f"{H}/Projects/../.ssh/id_rsa"), True),
    ("browser cookie jar",                  f("Read", f"{H}/Library/Cookies/x.binarycookies"), True),
    ("aws credentials",                     f("Read", f"{H}/.aws/credentials"), True),

    ("SELF-PROTECTION — unattended runs only", None, None),
    ("operator rewrites its permissions",   f("Write", f"{H}/Projects/nathanbot/config/permissions.json", True), True),
    ("owner edits them interactively",      f("Write", f"{H}/Projects/nathanbot/config/permissions.json"), False),
    ("operator writes a shell rc",          f("Write", f"{H}/.zshrc", True), True),
    ("owner writes their own shell rc",     f("Write", f"{H}/.zshrc"), False),
    ("operator disables the guard",         f("Write", f"{H}/.claude/hooks/x.py", True), True),
    ("operator installs a LaunchAgent",     f("Write", f"{H}/Library/LaunchAgents/x.plist", True), True),
    ("operator writes a git hook",          f("Write", f"{H}/Projects/nathanbot/.git/hooks/pre-commit", True), True),
    ("owner installs a git hook",           f("Write", f"{H}/Projects/nathanbot/.git/hooks/pre-commit"), False),
    ("tracked hook source is fine",         f("Write", f"{H}/Projects/nathanbot/scripts/hooks/pre-commit", True), False),

    ("NORMAL WORK — must not be fenced", None, None),
    ("write a project file",                f("Write", f"{H}/Projects/nathanbot/README.md", True), False),
    ("read a document",                     f("Read", f"{H}/Documents/notes.md", True), False),
    ("read a shell rc (write-only deny)",   f("Read", f"{H}/.zshrc", True), False),

    ("BASH GUARD", None, None),
    ("cat a private key",                   b(f"cat {H}/.ssh/id_rsa"), True),
    ("copy credentials out",                b(f"cp {H}/.aws/credentials /tmp/x"), True),
    ("commit MESSAGE naming a path",        b(f"git commit -m 'protect {H}/.ssh from agents'"), False),
    ("heredoc BODY naming a path",          b("cat > /tmp/a.py <<'EOF'\nx = '~/.ssh/id_rsa'\nEOF"), False),
    ("ordinary git status",                 b("git status"), False),
    ("operator un-gates itself",            b("nb perms set email.send always", operator=True), True),
    ("operator pushes",                     b("git push origin main", operator=True), True),
    ("owner pushes",                        b("git push origin main"), False),
    ("operator captures an idea",           b('nb add "an idea"', operator=True), False),
]


def main():
    fails = 0
    total = 0
    for desc, actual, expected in CASES:
        if actual is None:
            print(f"\n=== {desc} ===")
            continue
        total += 1
        ok = actual == expected
        fails += not ok
        got = "BLOCKED" if actual else "allowed"
        want = "BLOCKED" if expected else "allowed"
        print(f"  [{'ok  ' if ok else 'FAIL'}] {desc:38} {got:8}"
              + ("" if ok else f"  (expected {want})"))

    print(f"\n{total} assertions, {fails} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
