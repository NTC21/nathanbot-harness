#!/usr/bin/env python3
"""Shared path-guard logic for the Claude Code PreToolUse hooks.

Canonicalization is the whole ballgame here. On this machine (macOS/APFS) two
spellings reach the same file while os.path.realpath leaves them distinct:

  /System/Volumes/Data/Users/n/.zshrc  ==  /Users/n/.zshrc   (firmlink; same inode)
  ~/Projects/nathanbot/CONFIG/...      ==  .../config/...    (case-insensitive fs)

realpath collapses neither, so a denylist compared against realpath output is
bypassable by simply spelling the path differently. fcntl(F_GETPATH) asks the
kernel for the canonical path of an already-open fd and fixes both cases, so
that is what we match on. Verified on this machine before this file was written.
"""
import os
import fcntl

F_GETPATH = 50
HOME = os.path.expanduser("~")


def canonical(path):
    """Kernel-canonical absolute path: firmlinks collapsed, case normalized.

    Falls back to abspath/realpath for paths that do not exist yet (a Write
    creating a new file), canonicalizing the nearest existing ancestor so a
    denied directory cannot be dodged by naming a not-yet-created child.
    """
    if not path:
        return ""
    path = os.path.expanduser(str(path))
    if not os.path.isabs(path):
        path = os.path.abspath(path)

    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        # Does not exist (or unreadable): canonicalize the nearest existing
        # ancestor and re-attach the remainder.
        parent, tail = os.path.split(path)
        tails = [tail]
        while parent and parent != "/" and not os.path.exists(parent):
            parent, tail = os.path.split(parent)
            tails.append(tail)
        base = canonical(parent) if os.path.exists(parent) else os.path.realpath(parent)
        return os.path.join(base, *reversed(tails))
    try:
        res = fcntl.fcntl(fd, F_GETPATH, b"\0" * 1024)
        return res.split(b"\0")[0].decode()
    except OSError:
        return os.path.realpath(path)
    finally:
        os.close(fd)


def _h(*parts):
    return os.path.join(HOME, *parts)


# Where nathanbot lives. NB_ROOT env wins so a non-default checkout still
# protects its own rails; the conventional path is the fallback.
NB_ROOT = os.environ.get("NB_ROOT") or _h("Projects", "nathanbot")


# ── Tier 0: deny READ and WRITE. Credentials, session state, and anything whose
#    disclosure is not recoverable by rotating a password.
DENY_ALL = [
    # secrets / keys — the standard tool locations. Machine-specific vaults
    # (a personal ~/keys, per-business key dirs) belong in deny-local.txt, not
    # here: naming them in a shared file leaks what they are called.
    _h(".secrets"), _h(".ssh"), _h(".aws"), _h(".gnupg"), _h(".kube"), _h(".docker"),
    # tool credential files
    _h(".netrc"), _h(".npmrc"), _h(".yarnrc"), _h(".pypirc"), _h(".pgpass"),
    _h(".my.cnf"), _h(".rclone.conf"), _h(".git-credentials"),
    _h(".gem", "credentials"), _h(".m2", "settings.xml"),
    _h(".composer", "auth.json"), _h(".bundle", "config"),
    # OAuth token stores
    _h(".config", "gcloud"), _h(".config", "gh"), _h(".config", "stripe"),
    _h(".config", "rclone"), _h(".config", "configstore"),
    _h(".fastlane"), _h(".expo"), _h(".app-store"),
    # macOS keychains + privacy database
    _h("Library", "Keychains"), "/Library/Keychains", "/Library/Security",
    _h("Library", "Application Support", "com.apple.TCC"),
    _h("Library", "Accounts"), _h("Library", "IdentityServices"),
    # browser profiles — session cookies are an auth bypass with no password/2FA
    _h("Library", "Application Support", "Google", "Chrome"),
    _h("Library", "Application Support", "Chromium"),
    _h("Library", "Application Support", "BraveSoftware"),
    _h("Library", "Application Support", "Arc"),
    _h("Library", "Application Support", "Microsoft Edge"),
    _h("Library", "Application Support", "Firefox"),
    _h("Library", "Safari"), _h("Library", "Cookies"),
    _h("Library", "HTTPStorages"), _h("Library", "WebKit"),
    _h("Library", "Containers", "com.apple.Safari"),
    # password managers / wallets — blocked even though none are installed today,
    # because a denylist scoped to today's machine rots on the next brew install
    _h("Library", "Application Support", "1Password"),
    _h("Library", "Group Containers", "2BUA8C4S2C.com.1password"),
    _h("Library", "Application Support", "Bitwarden"),
    _h("Library", "Application Support", "KeePassXC"),
    _h("Library", "Application Support", "Exodus"),
    _h("Library", "Application Support", "Electrum"),
    _h("Library", "Application Support", "Ledger Live"),
    # private messages
    _h("Library", "Messages"), _h("Library", "Mail"),
    _h("Library", "Application Support", "Telegram Desktop"),
    _h("Library", "Application Support", "Signal"),
    _h("Library", "Application Support", "discord"),
]

# ── Tier 1: deny WRITE only. Reading is fine; writing is privilege escalation,
#    persistence, or self-un-gating.
DENY_WRITE = [
    # nathanbot's own guard rails — the operator must not be able to widen itself
    *[os.path.join(NB_ROOT, p) for p in (
        "config/permissions.json", "config/projects.json", "prompts",
        "server/server.py", "bin/nb", "bin/claudew",
    )],
    # Claude Code's own configuration and these very hooks
    _h(".claude", "settings.json"), _h(".claude", "hooks"),
    _h(".claude", "agents"),
    # git hooks — these execute on every commit, so a write here is arbitrary
    # code execution under the owner's identity at his next commit. Matched by
    # suffix (see _under_githooks) since they live in every repo, not one path.
    # shell + login persistence
    _h(".zshrc"), _h(".zprofile"), _h(".zshenv"), _h(".bashrc"),
    _h(".bash_profile"), _h(".profile"),
    _h("Library", "LaunchAgents"), "/Library/LaunchAgents", "/Library/LaunchDaemons",
    # system
    "/System", "/usr", "/bin", "/sbin", "/etc", "/private/etc", "/var", "/private/var",
    "/opt/homebrew/etc", "/Library/Preferences",
]


def _load_local_denies():
    """Extra deny-listed paths for THIS machine, one per line, # comments ok.

    Kept out of the tracked file on purpose: a personal key vault's name is
    itself information, and a shared/public copy of this guard should not
    enumerate one owner's directory layout. Missing file = no extras.

    Checked in two places: next to this file (where the symlinked install finds
    it) and the canonical ~/.claude/hooks/. The second matters because other code
    imports this module straight from the repo checkout, where deny-local.txt is
    correctly absent — without it those callers would silently get a weaker list
    than the live hooks enforce.
    """
    out = []
    seen = set()
    for f in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "deny-local.txt"),
              _h(".claude", "hooks", "deny-local.txt")):
        if f in seen:
            continue
        seen.add(f)
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.split("#", 1)[0].strip()
                    if line:
                        out.append(os.path.expanduser(line))
        except OSError:
            pass
    return out


DENY_ALL += _load_local_denies()


def _under(path, root):
    """True if `path` is `root` or sits beneath it. Both already canonical."""
    p, r = path.casefold(), canonical(root).casefold()
    return p == r or p.startswith(r.rstrip("/") + "/")


def is_operator():
    """True when running as the unattended nathanbot operator rather than as
    the owner interactively. The self-protection tier only makes sense for the
    former: a background run must not be able to widen its own permissions,
    while the owner editing their own shell rc or these hooks is ordinary work."""
    return bool(os.environ.get("NB_OPERATOR"))


def check(path, write, operator=None):
    """Return a human-readable reason string if this access is denied, else None.

    Credential paths (DENY_ALL) are denied in every context. The self-protection
    tier (DENY_WRITE) applies only to unattended operator runs.
    """
    if not path:
        return None
    if operator is None:
        operator = is_operator()
    c = canonical(path)

    # .git/hooks/* run on commit — deny for unattended runs in ANY repo.
    # Check the LITERAL path as well as the canonical one: a hook is often a
    # symlink to a tracked copy elsewhere (nathanbot installs its own that way),
    # and canonicalizing would resolve the dangerous location away while the
    # write still lands executable code in .git/hooks.
    literal = os.path.expanduser(str(path)).replace("\\", "/")
    if write and operator and ("/.git/hooks/" in c.replace("\\", "/")
                               or "/.git/hooks/" in literal):
        return ("git hooks execute on every commit, so writing one is arbitrary "
                "code execution under the owner's identity.\n"
                "   Denied for unattended runs. The owner installs hooks themselves "
                "(nathanbot: scripts/hooks/install.sh).")

    for root in DENY_ALL:
        if _under(c, root):
            return (f"'{root}' is on the nathanbot deny-list (read+write).\n"
                    f"   Credentials, session cookies, and private messages are off limits "
                    f"to automated tools — disclosure there is not fixable by rotating a password.")
    if write and operator:
        for root in DENY_WRITE:
            if _under(c, root):
                return (f"'{root}' is write-protected while running unattended "
                        f"(NB_OPERATOR).\n"
                        f"   An automated run must not change its own permissions, persist "
                        f"across sessions, or alter the system. The owner can edit this directly.")

    # The owner's standing rule: durable knowledge lives in nathanbot so every
    # harness sees it, never in Claude Code's project-local memory.
    if write and "/.claude/projects/" in c and "/memory/" in c and c.endswith(".md"):
        if os.path.basename(c) != "MEMORY.md":
            return ("this belongs in nathanbot, not Claude project memory.\n"
                    "   Use:  cd ~/Projects/nathanbot && bin/nb remember \"<the fact or rule>\"\n"
                    "   It auto-routes, and every harness sees it. (MEMORY.md index edits are allowed.)")
    return None
