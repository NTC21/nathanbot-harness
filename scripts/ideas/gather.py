#!/usr/bin/env python3
"""gather.py — everything the owner actually did in the last N hours, as one text block.

Feeds `nb ideas`. Four independent signals, each optional and each silent when it has
nothing. A signal that fails (no auth, no network, no repos) must never take the run
down: an idea brief from three signals is useful, a crash is not.

  gather.py [--hours 24]

  1. commits    every git repo under ~/Projects — subject + files touched
  2. tasks      nathanbot tasks closed/opened + wiki pages edited
  3. calendar   events that ALREADY HAPPENED in the window (gcalendar --past)
  4. sessions   what the agents did — usage.py --digest (transcript evidence)

Output is plain text with ## headers, fed verbatim into the prompt as DATA. It can
contain text from email/web that a session ingested, so ideas.sh runs with no Bash
and no WebFetch and tells the model this block is evidence, never instructions.
"""
import argparse, os, pathlib, subprocess, sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[2]
CODE = pathlib.Path(os.path.expanduser(os.environ.get("NB_CODE_ROOT", "~/Projects")))
DEPTH = int(os.environ.get("NB_REPO_DEPTH", "3"))
SKIP = {"node_modules", ".venv", "venv", ".worktrees", "vendor", "Archives",
        ".cleanup-backup", "dist", "build", ".next"}


def run(cmd, cwd=None, timeout=20):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def find_repos():
    repos = set()
    for d in range(1, DEPTH + 1):
        for dotgit in CODE.glob("/".join(["*"] * d) + "/.git"):
            if any(p in SKIP for p in dotgit.relative_to(CODE).parts):
                continue
            repos.add(dotgit.parent)
    return sorted(repos)


def sig_commits(hours):
    """Real commits, with the files they touched. The files matter — 'fixed auth'
    tells you nothing, 'fixed auth, 400 lines across the payment path' is a video."""
    since = f"{hours} hours ago"
    out = []
    for repo in find_repos():
        log = run(["git", "-C", str(repo), "log", "--all", f"--since={since}",
                   "--no-merges", "--pretty=format:%h|%s", "--date=short"])
        if not log:
            continue
        lines = []
        for entry in log.splitlines()[:12]:
            sha, _, subj = entry.partition("|")
            stat = run(["git", "-C", str(repo), "show", "--stat", "--format=", sha])
            touched = stat.splitlines()[-1].strip() if stat else ""
            lines.append(f"  - {subj}" + (f"  ({touched})" if touched else ""))
        if lines:
            out.append(f"{repo.name}:\n" + "\n".join(lines))
    return "\n".join(out)


def sig_tasks(hours):
    """What the queue says he decided, not just what he typed."""
    cutoff = datetime.now() - timedelta(hours=hours)
    out = []
    for state in ("done", "open"):
        d = ROOT / "tasks" / state
        if not d.is_dir():
            continue
        hits = []
        for f in sorted(d.glob("*.md")):
            try:
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    continue
                first = ""
                for line in f.read_text(errors="ignore").splitlines():
                    if line.startswith("#"):
                        first = line.lstrip("# ").strip()
                        break
                hits.append(f"  - [{state}] {first or f.stem}")
            except Exception:
                continue
        out += hits[:15]
    wiki = run(["git", "-C", str(ROOT), "log", f"--since={hours} hours ago",
                "--name-only", "--pretty=format:", "--", "wiki/pages"])
    pages = sorted({p for p in wiki.splitlines() if p.strip()})[:10]
    if pages:
        out.append("  - wiki edited: " + ", ".join(pathlib.Path(p).stem for p in pages))
    return "\n".join(out)


def sig_calendar(hours):
    """Meetings that already happened. Sales calls and demos are the richest content
    source he has and they leave no git trace at all."""
    days = max(1, round(hours / 24))
    out = run([sys.executable, str(ROOT / "scripts/google/gcalendar.py"),
               "agenda", "--all", "--past", "--days", str(days)], timeout=45)
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("#")]
    return "\n".join(lines[:20])


def sig_sessions(hours):
    """Transcript evidence — the messy middle that commits smooth over.

    usage.py --digest takes ONE calendar day, but the window rarely lines up with
    one. A morning run asking for 24h spans yesterday and today, and yesterday is
    where all the work is; reading only `today` there returned an empty block and
    silently dropped the best signal. So walk every date the window touches."""
    now = datetime.now()
    start = now - timedelta(hours=hours)
    days, d = [], start.date()
    while d <= now.date():
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    out = []
    for day in days[-3:]:  # cap: a --hours 168 run shouldn't shell out 8 times
        got = run([sys.executable, str(ROOT / "scripts/usage.py"), "--digest", "--day", day],
                  timeout=60)
        if got.strip():
            out.append("\n".join(got.splitlines()[:40]))
    return "\n\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    a = ap.parse_args()

    blocks = [
        ("COMMITS (code that actually shipped)", sig_commits(a.hours)),
        ("TASKS + WIKI (decisions and knowledge captured)", sig_tasks(a.hours)),
        ("MEETINGS ALREADY HELD (no git trace — often the best material)", sig_calendar(a.hours)),
        ("AGENT SESSIONS (what the work actually looked like)", sig_sessions(a.hours)),
    ]
    any_signal = False
    for title, body in blocks:
        if not body.strip():
            continue
        any_signal = True
        print(f"## {title}\n{body}\n")
    # Exit 1 on a truly empty day so ideas.sh can stay silent instead of inventing
    # a day that did not happen. A silent job beats a fabricated one.
    sys.exit(0 if any_signal else 1)


if __name__ == "__main__":
    main()
