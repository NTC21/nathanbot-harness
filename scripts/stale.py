#!/usr/bin/env python3
"""stale.py — catch memory that has drifted out of sync with reality.

The dangerous failure mode for nathanbot is not MISSING memory, it is CONFIDENTLY
WRONG memory: a future session reads a stale rule, follows it, and undoes work.
This session produced three live examples in one sitting:

  - career/MASTER.md carried "Summary (approved): ..." after the summary section
    had been deleted from the résumé. A later session would have re-added it.
  - MASTER.md pointed at a .tex source file after that file was deleted.
  - wiki/pages/career.md documented `nb jobs` after the command was removed.

None of that is detectable by nb audit, which checks structure (file sizes,
pointer wiring) rather than whether claims still hold. This checks the claims:

  1. file paths referenced in memory that no longer exist
  2. `nb <verb>` references where the verb is no longer a real subcommand
  3. dated "confirmed"/"as of" claims that have aged past a review horizon

Read-only. Reports; never edits.

  stale.py [--days N] [--quiet]
"""
import os
import re
import sys
import argparse
import subprocess
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")

# Memory surfaces: docs whose claims a future session will act on.
SCAN_DIRS = ["wiki", "career", "shared-memory", "prompts", "hermes"]
# .env.example is scanned because it is documentation that gets acted on: it told
# readers "real secrets live in ~/.secrets/ai-hub.env" for as long as that file
# did not exist. A doc pointing at a nonexistent secrets file is the same failure
# class as a stale wiki page, and worse in consequence — someone follows it and
# writes a key somewhere nothing loads.
SCAN_FILES = ["AGENTS.md", "README.md", ".env.example"]

# Illustrative rather than asserted: placeholders, examples, currency (~$40K reads
# as a ~/ path), URLs, API routes, and git remotes. A check that cries wolf gets
# ignored, so precision matters more than recall here.
PATH_IGNORE = re.compile(
    r"(<[^>]+>|\{[^}]+\}|\*|\.\.\.|example|foo|bar|baz|NNNN|YYYY|/path/to/|"
    r"your-|my-|\$|https?:|\.git$|@|/\*)", re.I)
# NOTE: ~/.secrets paths are deliberately NOT excluded. This checks EXISTENCE only
# (os.path.exists) and never opens a file, so it cannot leak a secret — and a doc
# pointing at a secrets file that was never created is exactly the drift worth
# catching. The Claude Code guard separately blocks agents from reading them.

# Only match things that are unambiguously filesystem paths:
#   ~/dir/thing        (home-anchored, at least one slash below ~)
#   knownrepodir/thing (anchored to a directory that actually exists in the repo)
REPO_DIRS = r"wiki|career|scripts|config|bin|server|prompts|tasks|shared-memory|hermes|public"
PATH_RE = re.compile(
    r"`(~/[\w.-]+/[\w./-]+|(?:" + REPO_DIRS + r")/[\w./-]+)`"      # inside backticks
    r"|(?<![\w/`])(~/[\w.-]+/[\w./-]+|(?:" + REPO_DIRS + r")/[\w./-]+\.\w+)")
NB_RE = re.compile(r"`?\bnb ([a-z][a-z-]{1,20})\b")
DATE_RE = re.compile(r"(?:confirmed|as of|verified|updated)[:\s(]*(\d{4})-(\d{2})-(\d{2})", re.I)


def nb_verbs():
    """Real subcommands, read from bin/nb's dispatch table."""
    verbs = set()
    try:
        src = open(os.path.join(ROOT, "bin", "nb")).read()
    except OSError:
        return verbs
    body = src.split("case ", 1)[-1]
    for m in re.finditer(r"^\s{2}([a-z][a-z|_-]*)\)", body, re.M):
        verbs.update(m.group(1).split("|"))
    return verbs


def scan_files():
    out = []
    for d in SCAN_DIRS:
        p = os.path.join(ROOT, d)
        for base, _, files in os.walk(p):
            if "/.git" in base:
                continue
            out += [os.path.join(base, f) for f in files if f.endswith(".md")]
    out += [os.path.join(ROOT, f) for f in SCAN_FILES if os.path.exists(os.path.join(ROOT, f))]
    return out


def resolve(tok):
    if tok.startswith("~/"):
        return os.path.join(HOME, tok[2:])
    return os.path.join(ROOT, tok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120,
                    help="flag dated claims older than this (default 120)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    verbs = nb_verbs()
    findings = []
    today = date.today()

    for path in scan_files():
        rel = os.path.relpath(path, ROOT)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue

        # Pages documenting an EXTERNAL system describe that system's layout, not
        # this machine's, so their paths are not claims about local reality.
        # Opt out with `stale-check: off` in frontmatter.
        if re.search(r"^stale-check:\s*off\b", text[:600], re.M):
            continue

        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith(">"):        # quoted/historical
                continue
            # Text that documents a removal necessarily names the removed thing —
            # that is memory working correctly, not drifting. Prose wraps, so judge
            # the surrounding sentence rather than the single line.
            window = " ".join(lines[max(0, i - 2):i + 1])
            if re.search(r"\b(removed|deleted|retired|deprecated|superseded|"
                         r"do not rebuild|no longer|was cut|formerly|since been|"
                         r"not configured|to enable|"
                         r"never\s+(been\s+)?(built|created|existed|shipped|configured))\b",
                         window, re.I):
                continue
            # "don't do this" examples deliberately name things that should not exist
            if "❌" in line:
                continue

            # 1. referenced paths that no longer exist
            for m in PATH_RE.finditer(line):
                tok = (m.group(1) or m.group(2) or "").strip()
                if not tok or PATH_IGNORE.search(tok):
                    continue
                if " " in tok and not tok.startswith("~/"):
                    continue
                if not (tok.startswith("~/") or "/" in tok):
                    continue
                if tok.endswith("/"):
                    tok = tok[:-1]
                target = resolve(tok)
                if not os.path.exists(target):
                    findings.append((rel, i, "missing path", tok))

            # 2. nb verbs that no longer exist
            for m in NB_RE.finditer(line):
                v = m.group(1)
                if verbs and v not in verbs and v not in {
                        "help", "project", "perms", "remember", "feedback"}:
                    findings.append((rel, i, "dead nb command", f"nb {v}"))

            # 3. dated claims past the review horizon
            for m in DATE_RE.finditer(line):
                try:
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    continue
                age = (today - d).days
                if age > a.days:
                    findings.append((rel, i, "aging claim", f"{d} ({age}d old)"))

    # dedupe
    seen, uniq = set(), []
    for f in findings:
        k = (f[0], f[2], f[3])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)

    if not uniq:
        if not a.quiet:
            print("✅ memory is consistent with reality — no stale references found")
        return 0

    by_kind = {}
    for rel, line, kind, detail in uniq:
        by_kind.setdefault(kind, []).append((rel, line, detail))

    print(f"\n\033[1m{len(uniq)} stale reference(s)\033[0m — memory that no longer "
          f"matches reality. A future session would act on these.\n")
    for kind, items in by_kind.items():
        print(f"  \033[1m{kind}\033[0m")
        for rel, line, detail in sorted(items):
            print(f"    {rel}:{line}  {detail}")
        print()
    print("  Fix by editing the file, or `nb remember` the corrected fact.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
