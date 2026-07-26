#!/usr/bin/env python3
"""SessionStart canary: prove the path guard is actually live.

The guards this replaced failed silently for their entire existence — they read
an env var that does not exist, so every check passed and nothing was ever
blocked. A disabled guard looks exactly like a guard with nothing to do, which
is why it went unnoticed. This runs known-denied probes through the real check()
and shouts if any come back allowed.

Never blocks a session; it prints a loud warning so a broken guard is visible
immediately rather than years later.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

H = os.path.expanduser("~")
# assembled from parts so this file does not itself contain a deny-listed literal
PROBES = [
    (os.path.join(H, "." + "ssh", "id_rsa"), False, "read a private ssh key"),
    (os.path.join(H, "." + "aws", "credentials"), False, "read cloud credentials"),
    (os.path.join(H, "Projects", "nathanbot", "config", "permissions.json"), True,
     "write its own permission config"),
]


def main():
    try:
        from nb_guard import check
    except Exception as e:
        print("NATHANBOT PATH GUARD IS DOWN - cannot import nb_guard (%s). "
              "Credentials are UNPROTECTED from automated tools." % e, file=sys.stderr)
        return 0

    # the write probe only applies to unattended runs, so evaluate it that way
    failed = [d for p, w, d in PROBES if not check(p, write=w, operator=True)]
    if failed:
        print("NATHANBOT PATH GUARD IS NOT BLOCKING: " + "; ".join(failed) +
              ". Check ~/.claude/hooks/. Credentials may be exposed.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
