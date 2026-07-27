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
  - THE INSTALLED GUARDS ARE THAT SAME SHAPE. install.sh symlinks
    ~/.claude/hooks/*.py to this directory, so writing the live guard was
    allowed for as long as the denylist named only the install location. Test
    the real symlinks, not a stand-in: the earlier case used a path that does
    not exist, which takes canonical()'s not-yet-created branch and passes for
    the wrong reason.
"""
import json
import os
import subprocess
import sys

HOOKS = os.path.dirname(os.path.abspath(__file__))
NB = os.path.dirname(HOOKS)
H = os.path.expanduser("~")
sys.path.insert(0, HOOKS)


def _run(hook, payload, operator=False, unattended=False):
    # BOTH must be cleared. claudew exports NB_UNATTENDED, so running this suite
    # from inside an agent session would otherwise set it for every case and flip
    # every "owner" assertion green-to-green for the wrong reason.
    env = dict(os.environ)
    env.pop("NB_OPERATOR", None)
    env.pop("NB_UNATTENDED", None)
    if operator:
        env["NB_OPERATOR"] = "1"
    if unattended:
        env["NB_UNATTENDED"] = "1"
    p = subprocess.run([sys.executable, os.path.join(HOOKS, hook)],
                       input=json.dumps(payload), capture_output=True, text=True, env=env)
    return p.returncode == 2


def f(tool, path, operator=False, unattended=False):
    field = "file_path" if tool in ("Read", "Write", "Edit") else "path"
    return _run("guard-paths.py", {"tool_name": tool, "tool_input": {field: path}},
                operator, unattended)


def b(cmd, cwd=H, operator=False, unattended=False):
    return _run("guard-bash.py",
                {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd},
                operator, unattended)


def _child_sees_flag(argv, extra_env=None):
    """Does this wrapper mark its CHILD unattended?

    Asserts on the child process's actual environment, not on whether a source
    file contains a string. The bug this suite exists for was precisely a guard
    that looked installed and did nothing — so "the export is in the file" is
    not the claim worth testing. NB_CLAUDE_BIN redirects claudew at printenv;
    argv passes through byte-identical, so the wrapper runs for real.
    """
    env = dict(os.environ)
    env.pop("NB_UNATTENDED", None)
    env.update(extra_env or {})
    p = subprocess.run(argv, capture_output=True, text=True, env=env)
    return p.stdout.strip() == "1"


def claudew_flag():
    """claudew now injects --session-id, so the stand-in binary must ignore argv.
    printenv used to work as the shim and stopped the moment the flag was added —
    the suite catching that is the point."""
    import tempfile
    fd, shim = tempfile.mkstemp(suffix=".sh")
    with os.fdopen(fd, "w") as fh:
        fh.write("#!/bin/sh\nprintenv NB_UNATTENDED\n")
    os.chmod(shim, 0o755)
    try:
        return _child_sees_flag([os.path.join(NB, "bin", "claudew"), "-p", "x"],
                                {"NB_CLAUDE_BIN": shim})
    finally:
        os.unlink(shim)


def rundue_flag():
    ok = _child_sees_flag(
        [os.path.join(NB, "scripts", "rundue.sh"), "_guardtest", "0", "0", "-", "-",
         "--", "/usr/bin/printenv", "NB_UNATTENDED"], {"NB_FORCE": "1"})
    # rundue stamps tasks/state/ on success; that dir is gitignored, but leaving
    # a stamp named after a test is litter.
    try:
        os.remove(os.path.join(NB, "tasks", "state", "_guardtest.last"))
    except OSError:
        pass
    return ok


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

    ("SYMLINKED RAILS — deny BOTH ends of the link", None, None),
    ("rewrite the live guard",              f("Write", f"{H}/.claude/hooks/nb_guard.py", True), True),
    ("...via its repo-side path",           f("Write", f"{NB}/claude-hooks/nb_guard.py", True), True),
    ("...the bash guard",                   f("Write", f"{H}/.claude/hooks/guard-bash.py", True), True),
    ("...the canary that detects this",     f("Write", f"{H}/.claude/hooks/guard-canary.py", True), True),
    ("...the machine's extra deny list",    f("Write", f"{H}/.claude/hooks/deny-local.txt", True), True),
    ("rewrite the identity registry",       f("Write", f"{NB}/config/accounts.json", True), True),
    ("rewrite the canonical entry doc",     f("Write", f"{NB}/AGENTS.md", True), True),
    ("rewrite global Claude memory",        f("Write", f"{H}/.claude/CLAUDE.md", True), True),
    ("owner edits his own guards",          f("Write", f"{NB}/claude-hooks/nb_guard.py"), False),
    ("owner edits AGENTS.md",               f("Write", f"{NB}/AGENTS.md"), False),
    ("reading the guard is fine",           f("Read", f"{H}/.claude/hooks/nb_guard.py", True), False),
    ("rewrite the repo's Claude settings",  f("Write", f"{NB}/.claude/settings.json", True), True),
    ("rewrite a specialist agent",          f("Write", f"{NB}/.claude/agents/research.md", True), True),
    ("owner edits his own agents",          f("Write", f"{NB}/.claude/agents/research.md"), False),

    ("UNATTENDED — the scheduled-job tier, with no NB_OPERATOR", None, None),
    ("scheduled job rewrites permissions",  f("Write", f"{NB}/config/permissions.json", unattended=True), True),
    ("scheduled job edits the CLI",         f("Write", f"{NB}/bin/nb", unattended=True), True),
    ("scheduled job edits its own wrapper", f("Write", f"{NB}/bin/claudew", unattended=True), True),
    ("scheduled job disables the guard",    f("Write", f"{H}/.claude/hooks/nb_guard.py", unattended=True), True),
    ("scheduled job edits settings.json",   f("Write", f"{H}/.claude/settings.json", unattended=True), True),
    ("scheduled job installs a LaunchAgent",f("Write", f"{H}/Library/LaunchAgents/x.plist", unattended=True), True),
    ("scheduled job writes a shell rc",     f("Write", f"{H}/.zshrc", unattended=True), True),
    ("scheduled job writes a git hook",     f("Write", f"{NB}/.git/hooks/pre-commit", unattended=True), True),
    ("scheduled job edits its prompts",     f("Write", f"{NB}/prompts/operator.md", unattended=True), True),
    ("scheduled job pushes",                b("git push origin master", unattended=True), True),
    ("scheduled job un-gates itself",       b("nb perms set email.send always", unattended=True), True),

    ("UNATTENDED — but the jobs must still do their actual work", None, None),
    ("evolve writes a proposal task",       f("Write", f"{NB}/tasks/open/t-9999-x.md", unattended=True), False),
    ("evolve fixes a wiki page",            f("Edit",  f"{NB}/wiki/pages/nathanbot.md", unattended=True), False),
    ("learn updates the model of the owner",   f("Edit",  f"{NB}/shared-memory/OVERVIEW.md", unattended=True), False),
    ("groom archives a task",               f("Write", f"{NB}/tasks/archive/done-2026-07.md", unattended=True), False),
    ("scheduled job still reads freely",    f("Read",  f"{H}/.zshrc", unattended=True), False),
    ("scheduled job runs its own verbs",    b("nb brief", unattended=True), False),
    ("owner still edits bin/nb himself",    f("Write", f"{NB}/bin/nb"), False),

    ("WIRING — the flag reaches the child, not just the source file", None, None),
    ("claudew marks its child unattended",  claudew_flag(), True, ("set", "UNSET")),
    ("rundue.sh marks its child too",       rundue_flag(), True, ("set", "UNSET")),

    ("MCP TOOLS — the FIELDS map fails open, so unknown tools get screened", None, None),
    ("Word opens a credential file",
     _run("guard-paths.py", {"tool_name": "mcp__Word__open_document",
                             "tool_input": {"file_path": f"{H}/.ssh/id_rsa"}}), True),
    ("browser uploads one, nested arg",
     _run("guard-paths.py", {"tool_name": "mcp__chrome__file_upload",
                             "tool_input": {"files": [{"path": f"{H}/.aws/credentials"}]}}), True),
    ("...but an ordinary document is fine",
     _run("guard-paths.py", {"tool_name": "mcp__Word__open_document",
                             "tool_input": {"file_path": f"{H}/Documents/notes.docx"}}), False),
    ("...and a non-path argument is fine",
     _run("guard-paths.py", {"tool_name": "mcp__x__search",
                             "tool_input": {"query": "how do I read ~/.ssh keys"}}), False),

    ("NORMAL WORK — must not be fenced", None, None),
    ("write a project file",                f("Write", f"{H}/Projects/nathanbot/README.md", True), False),
    ("read a document",                     f("Read", f"{H}/Documents/notes.md", True), False),
    ("read a shell rc (write-only deny)",   f("Read", f"{H}/.zshrc", True), False),

    ("BASH GUARD", None, None),
    ("cat a private key",                   b(f"cat {H}/.ssh/id_rsa"), True),
    ("copy credentials out",                b(f"cp {H}/.aws/credentials /tmp/x"), True),
    ("commit MESSAGE naming a path",        b(f"git commit -m 'protect {H}/.ssh from agents'"), False),
    ("heredoc BODY naming a path",          b("cat > /tmp/a.py <<'EOF'\nx = '~/.ssh/id_rsa'\nEOF"), False),
    # the redirect is legal mid-command, so the body starts on the NEXT line
    ("heredoc with the tag mid-command",    b("git commit -F - <<'MSG' && git log\nsee ~/.ssh/id_rsa\nMSG"), False),
    ("ordinary git status",                 b("git status"), False),
    ("operator un-gates itself",            b("nb perms set email.send always", operator=True), True),
    ("operator pushes",                     b("git push origin main", operator=True), True),
    ("owner pushes",                        b("git push origin main"), False),
    ("operator captures an idea",           b('nb add "an idea"', operator=True), False),

    # Each of these was verified ALLOWED against the real hook before the fix.
    # The destination of cp/mv/ln is never the first argument, and the scan used
    # to stop at the first — so the write tier was unreachable from Bash.
    ("BASH GUARD — writes the arg scan used to miss", None, None),
    ("cp OVER the live guard",               b(f"cp /tmp/e.py {H}/.claude/hooks/guard-bash.py", unattended=True), True),
    ("mv over it",                           b(f"mv /tmp/e.py {H}/.claude/hooks/nb_guard.py", unattended=True), True),
    ("symlink over it",                      b(f"ln -sf /tmp/e.py {H}/.claude/hooks/nb_guard.py", unattended=True), True),
    ("rm the whole hooks dir",               b(f"rm -rf {H}/.claude/hooks", unattended=True), True),
    ("sed -i the guard",                     b(f"sed -i '' 's/x/y/' {H}/.claude/hooks/guard-bash.py", unattended=True), True),
    ("truncate it to nothing",               b(f": > {H}/.claude/hooks/guard-bash.py", unattended=True), True),
    ("append to a shell rc",                 b(f"echo evil >> {H}/.zshrc", unattended=True), True),
    ("clobber permissions.json",             b(f"echo '{{}}' > {NB}/config/permissions.json", unattended=True), True),
    ("chmod -x the guard",                   b(f"chmod -x {H}/.claude/hooks/guard-bash.py", unattended=True), True),
    ("launchctl kickstart",                  b("launchctl kickstart gui/501/com.x", unattended=True), True),
    ("prose flag no longer hides a path",    b(f"cat -b {H}/.ssh/id_rsa"), True),

    ("BASH GUARD — ordinary work must still pass", None, None),
    ("read a rail file",                     b(f"cat {NB}/bin/nb", unattended=True), False),
    ("grep the repo",                        b(f"grep -rn TODO {NB}/scripts", unattended=True), False),
    ("rm build junk",                        b(f"rm -rf {NB}/node_modules", unattended=True), False),
    ("cp within the repo",                   b(f"cp {NB}/README.md /tmp/r.md", unattended=True), False),
    ("write a task file",                    b(f"echo x > {NB}/tasks/open/t-1.md", unattended=True), False),
    ("owner edits his own rc",               b(f"echo x >> {H}/.zshrc"), False),
    ("commit message naming a rail",         b(f"git commit -m 'protect {NB}/bin/nb'", unattended=True), False),
]


def main():
    fails = 0
    total = 0
    for desc, actual, expected, *rest in CASES:
        if actual is None:
            print(f"\n=== {desc} ===")
            continue
        total += 1
        # most cases assert "was it blocked?"; the wiring ones assert a plain
        # boolean, so they carry their own labels rather than misreport as
        # "allowed" when what they mean is "the flag never reached the child"
        yes, no = rest[0] if rest else ("BLOCKED", "allowed")
        ok = actual == expected
        fails += not ok
        got = yes if actual else no
        want = yes if expected else no
        print(f"  [{'ok  ' if ok else 'FAIL'}] {desc:38} {got:8}"
              + ("" if ok else f"  (expected {want})"))

    print(f"\n{total} assertions, {fails} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
