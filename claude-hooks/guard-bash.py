#!/usr/bin/env python3
"""PreToolUse guard for Bash.

Two jobs:
  1. Keep the /infrastructure merge rule the owner wanted (it was silently
     dead — the old hook read $CLAUDE_TOOL_INPUT, which does not exist).
  2. Catch obvious shell reads/writes of deny-listed paths.

HONEST SCOPE: (2) is defense-in-depth, not a boundary. A shell is far too
expressive to filter reliably — variable expansion, base64, xxd, a here-doc into
python3, or a helper script written first and run second all evade pattern
matching. The real boundary is not granting broad Bash to an unattended run in
the first place. This catches the careless case, not a determined one.

exit 0 = allow, exit 2 = deny.
"""
import sys
import json
import os
import re
import shlex

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nb_guard import check, DENY_ALL, canonical, is_unattended  # noqa: E402

# Commands whose arguments are plainly file paths worth screening.
FILE_CMDS = {
    "cat", "less", "more", "head", "tail", "bat", "strings", "xxd", "od",
    "cp", "mv", "rsync", "scp", "ln", "install",
    "sed", "awk", "grep", "rg", "ag", "open", "plutil", "defaults",
    "security", "base64", "shred", "srm", "tee", "dd",
    # destructive verbs that were absent, so `rm -rf ~/.claude/hooks` walked past
    "rm", "rmdir", "chmod", "chown", "ditto", "unzip", "truncate",
}

# Where the write actually lands, so a read arg is not mistaken for a write and
# — more importantly — a write arg is not mistaken for a read.
WRITE_LAST = {"cp", "mv", "rsync", "scp", "ln", "install"}   # sources read, dest written
WRITE_ALL = {"tee", "dd", "shred", "srm", "rm", "rmdir", "chmod", "chown",
             "truncate", "ditto", "unzip"}

DENY_CANON = [canonical(p).casefold() for p in DENY_ALL]


def strip_heredocs(cmd):
    """Drop heredoc bodies. They are file CONTENT, not arguments — a script whose
    text merely mentions a credential path is not an attempt to read one, and
    treating it as one blocks ordinary work (it blocked writing this guard).

    [^\\n]* after the tag matters: the redirect is legal anywhere on the line, so
    `git commit -F - <<'MSG' && git log` puts the body on the NEXT line. Anchoring
    the tag to end-of-line missed that form entirely and left the body in — which
    blocked a commit whose message quoted the paths being protected.
    """
    return re.sub(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\2\b", "", cmd, flags=re.S)


# Flags whose argument is human prose, not a path: a commit message describing a
# credential directory is not an attempt to read one.
# -b is deliberately NOT here. It is `gh pr create -b` but also `cat -b`,
# `sort -b` and `base64 -b`, so honouring it swallowed the very next token and
# `cat -b ~/.ssh/id_rsa` sailed through. A prose flag that collides with a real
# file flag is worth losing.
MSG_FLAGS = ("-m", "--message", "-am", "--body", "--description", "--title")


def strip_message_args(cmd):
    """Drop the argument that follows a message-carrying flag."""
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return cmd
    out, skip = [], False
    for tok in parts:
        if skip:
            skip = False
            continue
        if tok in MSG_FLAGS:
            skip = True
            continue
        if any(tok.startswith(f + "=") for f in MSG_FLAGS):
            continue
        out.append(tok)
    return " ".join(out)


def touches_denied(cmd):
    """Look for a deny-listed path among the command's arguments."""
    low = strip_message_args(strip_heredocs(cmd)).casefold()
    for root in DENY_CANON:
        # match the canonical form and the common ~ spelling
        short = root.replace(os.path.expanduser("~").casefold(), "~")
        if root in low or short in low:
            return root
    return None


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        print("BLOCKED — bash guard could not parse its hook payload, failing closed.",
              file=sys.stderr)
        return 2

    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not cmd:
        return 0
    cwd = payload.get("cwd", "")

    # 0. self-un-gating (unattended runs only). allowedTools patterns match by
    #    prefix, so a grant of `nb perms` also grants `nb perms set`. The owner
    #    running this themselves is ordinary configuration.
    # imported, not a second copy of the env check — two copies of "am I
    # unattended?" is exactly how the flag's two meanings drifted apart
    if is_unattended():
        SELF_UNGATE = [
            r"\bnb\s+perms\s+set\b",         # rewrite its own permission levels
            r"\bnb\s+(sync|push)\b",          # push without approval
            r"\bnb\s+(evolve|learn|tidy|groom)\b.*--apply",   # self-modification
            r"\bgit\s+push\b",
            r"\bchmod\s+.*(/\.claude/|/nathanbot/(config|prompts)/)",
            # kickstart/start/bootout restart a job under a rewritten plist, so
            # load|bootstrap|enable alone was not the whole persistence surface
            r"\blaunchctl\s+(load|bootstrap|enable|kickstart|start|bootout)\b",
        ]
        for pat in SELF_UNGATE:
            if re.search(pat, cmd):
                print(f"BLOCKED — '{pat}' is not permitted while running unattended "
                      f"(NB_OPERATOR/NB_UNATTENDED). An automated run must not change its own "
                      f"permissions, push, or install persistence. Stage it for "
                      f"the owner to approve instead.", file=sys.stderr)
                return 2

    # 1. infrastructure merge rule — the owner reviews and merges those
    if re.search(r"\bgh\s+pr\s+merge\b", cmd):
        if "/infrastructure" in cmd or "/infrastructure" in cwd:
            print("BLOCKED — merges to infrastructure are not allowed; "
                  "the owner reviews and merges those PRs.", file=sys.stderr)
            return 2

    # 2. obvious access to deny-listed paths
    hit = touches_denied(cmd)
    if hit:
        print(f"BLOCKED by nathanbot path guard — this command references "
              f"'{hit}', which is deny-listed.\n"
              f"   Credentials and session state are off limits to automated tools.",
              file=sys.stderr)
        return 2

    # 3. per-argument check for the common file commands, so a relative path or
    #    a symlink into a denied directory is still caught. This is also the ONLY
    #    place the write tier (DENY_WRITE) is reachable — the string scan above
    #    cannot tell a read from a write, and DENY_WRITE paths are legitimately
    #    readable (`cat bin/nb` is ordinary work).
    try:
        # strip heredocs first: their body is file CONTENT, not arguments. Now
        # that this scans every argument rather than stopping at the first, a
        # script whose text merely mentions a credential path would otherwise
        # read as an attempt to open one.
        parts = shlex.split(strip_heredocs(cmd))
    except ValueError:
        return 0                      # unbalanced quotes: let the shell reject it

    def deny(what, arg):
        print(f"BLOCKED by nathanbot path guard — {what} targeting "
              f"'{arg}', which resolves into a deny-listed location.",
              file=sys.stderr)

    def pathish(a):
        return not a.startswith("-") and ("/" in a or a.startswith("~"))

    # 3a. redirect targets are writes no matter what command produced them —
    #     `: > ~/.claude/hooks/guard-bash.py` never reaches a FILE_CMD at all.
    for i, tok in enumerate(parts):
        tgt = None
        if tok in (">", ">>") and i + 1 < len(parts):
            tgt = parts[i + 1]
        elif re.match(r"^>>?[^>|&]", tok):
            tgt = tok.lstrip(">")
        if tgt and pathish(tgt) and check(tgt, write=True):
            deny("redirect", tgt)
            return 2

    # 3b. every argument of a file command, not just the first. For cp/mv/ln the
    #     DESTINATION is the write and it is never the first argument — which is
    #     how `cp /tmp/evil.py ~/.claude/hooks/guard-bash.py` used to pass.
    for i, tok in enumerate(parts):
        base = os.path.basename(tok)
        if base not in FILE_CMDS:
            continue
        rest = parts[i + 1:]
        for j, sep in enumerate(rest):
            if sep in {"|", "&&", "||", ";"}:
                rest = rest[:j]
                break
        args = [a for a in rest if pathish(a)]
        if not args:
            continue
        # sed -i / perl -i rewrite in place; without it sed only reads
        inplace = any(a == "-i" or a.startswith("-i") and len(a) < 4 for a in rest)
        for a in args:
            if base in WRITE_ALL:
                w = True
            elif base in WRITE_LAST:
                w = a is args[-1]
            else:
                w = inplace and base in {"sed", "perl"}
            if check(a, write=w):
                deny(f"'{base}'", a)
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
