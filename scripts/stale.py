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
#
# public/ docs/ capabilities/ workspace*/ were added 2026-07-26 after a full audit
# found ~30 false claims while this reported clean. Every one of them lived in a
# directory this list did not name — including public/, which was already in
# REPO_DIRS below (so its paths were link TARGETS) but was never itself scanned.
# capabilities/ matters most: its guidance is composed into other repos'
# CAPABILITIES.md, and the copy there had the email-identity rule inverted.
SCAN_DIRS = ["wiki", "career", "shared-memory", "prompts", "hermes",
             "public", "docs", "capabilities",
             "workspace", "workspace-admin", "workspace-coding",
             "workspace-creative", "workspace-research",
             # _proposed/ and _refine/ only. The 10 vendored upstream skills
             # document Cloudflare's layout, not this machine's, and scanning
             # them would produce dozens of false "missing path" findings.
             "skills/_proposed", "skills/_refine"]
# .env.example is scanned because it is documentation that gets acted on: it told
# readers "real secrets live in ~/.secrets/ai-hub.env" for as long as that file
# did not exist. A doc pointing at a nonexistent secrets file is the same failure
# class as a stale wiki page, and worse in consequence — someone follows it and
# writes a key somewhere nothing loads.
SCAN_FILES = ["AGENTS.md", "README.md", "START-HERE.md", ".env.example"]

# Bare filenames a doc claims exist. PATH_RE below only matches paths WITH a
# directory component, so `docx2pdf.sh` and `.mcp.json` — both named as real
# tooling in docs, neither present anywhere — were invisible to it. Only
# script-ish extensions, and only inside backticks, to keep the false-positive
# rate near zero: prose mentioning "config.json" generically should not fire.
BARE_FILE_RE = re.compile(r"`([\w.-]+\.(?:sh|py|js|ts|tex|plist))`")

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
REPO_DIRS = (r"wiki|career|scripts|config|bin|server|prompts|tasks|shared-memory"
             r"|hermes|public|skills|capabilities")
# The backtick branch stops at a space instead of requiring the closing backtick,
# because docs backtick whole COMMANDS: `scripts/setup-fallback.sh install`. The
# old pattern needed the backticks to wrap a bare path, and the plain branch's
# lookbehind then rejected it for being preceded by a backtick — so every
# backticked command-with-arguments was invisible. That is the exact shape of the
# claim (a removed installer, still being recommended) this was written to catch.
PATH_RE = re.compile(
    r"`(~/[\w.-]+/[\w./-]+|(?:" + REPO_DIRS + r")/[\w./-]+)(?=[\s`])"   # backticked
    r"|(?<![\w/`])(~/[\w.-]+/[\w./-]+|(?:" + REPO_DIRS + r")/[\w./-]+\.\w+)")
# Backtick, line start, or after a shell prompt/pipe — NOT mid-sentence. Prose
# like "put nb on your PATH" was reported as a dead `nb on` command.
NB_RE = re.compile(r"(?:`|^|\$ |\| )nb ([a-z][a-z-]{1,20})\b", re.M)
DATE_RE = re.compile(r"(?:confirmed|as of|verified|updated)[:\s(]*(\d{4})-(\d{2})-(\d{2})", re.I)


def nb_verbs(canonical_only=False):
    """Real subcommands, read from bin/nb's dispatch table.

    canonical_only keeps just the first name in each `a|b|c)` arm. Staleness wants
    every spelling (a doc naming an alias is not stale); usage analysis wants the
    canonical one, or `proj`, `talk` and `say` each count as separate commands
    the owner "never uses" while he uses the verb they alias.
    """
    verbs = set()
    try:
        src = open(os.path.join(ROOT, "bin", "nb")).read()
    except OSError:
        return verbs
    body = src.split("case ", 1)[-1]
    for m in re.finditer(r"^\s{2}([a-z][a-z|_-]*)\)", body, re.M):
        names = m.group(1).split("|")
        verbs.update(names[:1] if canonical_only else names)
    return verbs


def scan_files():
    out = []
    for d in SCAN_DIRS:
        p = os.path.join(ROOT, d)
        for base, _, files in os.walk(p):
            if "/.git" in base:
                continue
            # .yaml too: capabilities/ are YAML, and their `guidance:` blocks are
            # composed verbatim into other repos' CAPABILITIES.md — prose an agent
            # acts on, in exactly the way a wiki page is.
            out += [os.path.join(base, f) for f in files
                    if f.endswith((".md", ".yaml", ".yml"))]
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

        # Point-in-time records: a dated session note and a dated audit report say
        # what was true THEN. "Exported 63 stashes to ~/Projects/.stash-backup-
        # 2026-07-21/" is a correct record of that day even after the directory is
        # deleted, and a dated audit necessarily quotes the broken things it found.
        # Curated state files (workspace-*/MEMORY.md, wiki pages) are the opposite:
        # they assert what is true NOW, so they stay in scope.
        if re.search(r"/memory/\d{4}-\d{2}-\d{2}\.md$", rel) or \
           re.search(r"^docs/audit-\d{4}-\d{2}-\d{2}\.md$", rel) or \
           re.search(r"^wiki/daily/", rel):
            continue

        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith(">"):        # quoted/historical
                continue
            # Text that documents a removal necessarily names the removed thing —
            # that is memory working correctly, not drifting. Prose wraps, so judge
            # the surrounding sentence rather than the single line.
            # 5 lines back, not 2: these are wrapped markdown paragraphs. The
            # liked-repos entry says "NOT CONFIGURED ... has never been created"
            # and then gives setup instructions three lines later — the mkdir in
            # those instructions is not a claim the directory exists.
            window = " ".join(lines[max(0, i - 5):i + 1])
            if re.search(r"\b(removed|deleted|retired|deprecated|superseded|gone|"
                         r"do not rebuild|no longer|was cut|formerly|since been|"
                         r"not configured|"
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
                # public/ is setup instructions for a TEMPLATE USER, so a ~/ path
                # there describes their machine, not this one — "put your key in
                # ~/.secrets/picovoice/access_key" is a correct instruction even
                # though no such file exists here. Repo-relative paths in public/
                # ARE still checked, which is the case that matters: it is how
                # `scripts/setup-fallback.sh` survived in a shipped doc for a day
                # after being deleted.
                if rel.startswith("public/") and tok.startswith("~/"):
                    continue
                # A skill documents the project it is ABOUT, not nathanbot. A
                # per-project release skill correctly names `scripts/demo.sh`,
                # which lives in THAT repo. Checking those against this root reports a
                # missing path for every accurate skill, which is how a check
                # gets ignored. Marker integrity is audit.sh's job instead.
                if rel.startswith("skills/"):
                    continue
                if " " in tok and not tok.startswith("~/"):
                    continue
                if not (tok.startswith("~/") or "/" in tok):
                    continue
                if tok.endswith("/"):
                    tok = tok[:-1]
                target = resolve(tok)
                # public/ is the template for a DIFFERENT repo, and
                # release-public.sh rewrites some paths on the way out (notably
                # wiki/pages/owner.md -> owner.md). Resolving its repo-relative
                # claims against this root reported a permanent false positive
                # for a line that is correct where it actually ships.
                if not os.path.exists(target) and rel.startswith("public/"):
                    pub = os.environ.get("NB_PUBLIC_REPO",
                                         os.path.join(HOME, "Projects", "nathanbot-harness"))
                    if os.path.exists(os.path.join(pub, tok)):
                        continue
                if not os.path.exists(target):
                    findings.append((rel, i, "missing path", tok))

            # 1b. bare filenames claimed as real tooling. PATH_RE needs a directory
            #     component, so `docx2pdf.sh` and `.mcp.json` — both named in docs
            #     as things you run, neither existing anywhere — slipped past it.
            for m in BARE_FILE_RE.finditer(line):
                name = m.group(1)
                if PATH_IGNORE.search(name):
                    continue
                roots = [ROOT, os.path.join(HOME, "Projects")]
                hits = subprocess.run(
                    ["find", *[r for r in roots if os.path.isdir(r)],
                     "-name", name, "-not", "-path", "*/.git/*",
                     "-not", "-path", "*/.venv/*",
                     "-not", "-path", "*/node_modules/*", "-print", "-quit"],
                    capture_output=True, text=True).stdout.strip()
                if not hits and not os.path.exists(os.path.join(HOME, name)):
                    findings.append((rel, i, "missing file", name))

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
    # 3, not 1. Finding drift is a RESULT; an uncaught exception also exits
    # non-zero, and if both were 1 then tagging `stale` as "non-zero on purpose"
    # in the telemetry log would hide every real traceback behind ~22 working
    # runs. 1 stays reserved for genuine failure.
    # Every consumer reads stdout, not the exit code (bin/nb:680, audit.sh:180,
    # scripts/hooks/pre-commit:17, scripts/hooks/pre-push:55), so this is free.
    return 3


if __name__ == "__main__":
    sys.exit(main())
