#!/usr/bin/env python3
"""Repo awareness — nathanbot notices what you ship. Finds every git repo under
your code root (INCLUDING nested ones like Foo/foo), tracks the last commit
it saw per repo, and on new commits surfaces them. This is what watch.sh missed:
it only saw top-level repos and only 'dirty tree', never commits/pushes.

  repo-activity.py            detect new commits since last run -> notify (deliver.sh)
  repo-activity.py --report   print recent activity across all repos, no state change
  repo-activity.py --seed     record current state silently (no notifications)

  NB_CODE_ROOT   where to scan (default ~/Projects)
  NB_REPO_DEPTH  how deep to look for .git (default 3 — catches one nesting level)
"""
import json, os, sys, subprocess, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
CODE = pathlib.Path(os.path.expanduser(os.environ.get("NB_CODE_ROOT", "~/Projects")))
DEPTH = int(os.environ.get("NB_REPO_DEPTH", "3"))
STATE = ROOT / "tasks" / ".repo-activity.json"
SKIP = {"node_modules", ".venv", "venv", ".worktrees", "vendor", "Archives", ".cleanup-backup"}
# repos that auto-sync fine but whose pushes are too frequent/trivial to ping about
MUTE_NOTIFY = {"intro-sandbox"}


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=15)
    return r.stdout.strip() if r.returncode == 0 else ""


def find_repos():
    # glob explicit depths (1..DEPTH) so we never crawl into node_modules/.venv
    repos = set()
    for d in range(1, DEPTH + 1):
        for dotgit in CODE.glob("/".join(["*"] * d) + "/.git"):
            if any(p in SKIP for p in dotgit.relative_to(CODE).parts):
                continue
            repos.add(dotgit.parent)
    return sorted(repos)


def remote_ref(repo):
    """The remote default-branch ref (e.g. 'origin/main'), or None if no remote.
    This is where PR merges land — the real 'shipped' signal, not local HEAD."""
    if not git(repo, "remote"):
        return None
    sym = git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if sym:
        return sym.replace("refs/remotes/", "")
    for cand in ("origin/main", "origin/master"):
        if git(repo, "rev-parse", "--verify", "--quiet", cand):
            return cand
    return None


def tip(repo, fetch=False):
    """The 'shipped' tip: remote default branch if there is one (fetched fresh),
    else local HEAD. Reports how far the local checkout is behind."""
    ref = remote_ref(repo)
    if fetch and ref:
        subprocess.run(["git", "-C", str(repo), "fetch", "origin", "--quiet"],
                       timeout=25, capture_output=True)
    use = ref or "HEAD"
    h = git(repo, "log", "-1", "--format=%H\x1f%s\x1f%ct", use)
    if not h:
        return None
    sha, subj, ts = h.split("\x1f")
    behind = git(repo, "rev-list", "--count", f"HEAD..{ref}") if ref else "0"
    return {"sha": sha, "subject": subj, "ts": int(ts), "ref": use,
            "remote": bool(ref), "behind": behind or "0"}


def new_subjects(repo, since_sha, ref):
    if not since_sha:
        return []
    return [l for l in git(repo, "log", f"{since_sha}..{ref}", "--format=%s").splitlines() if l.strip()]


def auto_sync(repo):
    """Fast-forward a stale checkout — but ONLY when it's provably safe:
    clean working tree, an upstream set, behind>0, and NOT ahead (pure ff).
    `git merge --ff-only` refuses anything else, so this can never merge,
    conflict, or overwrite uncommitted work. Returns #commits pulled (0 if skipped).
    Disable with NB_AUTOPULL=0."""
    if os.environ.get("NB_AUTOPULL", "1") == "0":
        return 0
    # "dirty" ignores local-only noise (Claude Code settings, macOS junk) — nearly
    # every repo has an uncommitted .claude/, which would otherwise block every ff.
    # git merge --ff-only is still the hard backstop: it aborts rather than clobber
    # any real local change or untracked file, so relaxing this check stays safe.
    NOISE = (".claude/", ".DS_Store")
    dirty = [l for l in git(repo, "status", "--porcelain").splitlines()
             if l.strip() and not any(n in l for n in NOISE)]
    if dirty:
        return 0
    if not git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
        return 0                                           # no upstream
    behind = git(repo, "rev-list", "--count", "HEAD..@{u}") or "0"
    ahead = git(repo, "rev-list", "--count", "@{u}..HEAD") or "0"
    if behind == "0" or ahead != "0":                      # nothing to do, or diverged (needs you)
        return 0
    r = subprocess.run(["git", "-C", str(repo), "merge", "--ff-only", "@{u}"],
                       capture_output=True, text=True, timeout=30)
    return int(behind) if r.returncode == 0 else 0


def deliver(title, body):
    subprocess.run([str(ROOT / "scripts" / "deliver.sh"), title, body],
                   timeout=30, capture_output=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    fetch = mode != "--report"                 # notifier/seed fetch; report stays fast+offline
    state = {}
    try:
        state = json.loads(STATE.read_text())
    except Exception:
        pass

    lines = []
    for repo in find_repos():
        t = tip(repo, fetch=fetch)
        if not t:
            continue
        name = repo.name
        seen = state.get(str(repo), {}).get("sha")
        if mode == "--report":
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc).timestamp() - t["ts"]) / 3600
            note = f" · local {t['behind']} behind" if t["behind"] not in ("0", "") else ""
            lines.append(f"  {name:22} {t['subject'][:46]:48} ({age:.0f}h{note})")
            continue
        state[str(repo)] = {"sha": t["sha"], "ts": t["ts"]}
        pulled = auto_sync(repo)                    # keep the local checkout current, safely
        if pulled:
            print(f"synced {name}: +{pulled} (ff)", flush=True)
        if mode == "--seed" or seen == t["sha"]:
            continue
        subs = new_subjects(repo, seen, t["ref"])
        if subs and seen and name not in MUTE_NOTIFY:   # only notify on genuinely new work
            where = "pushed" if t["remote"] else "committed"
            body = "\n".join(f"• {c[:70]}" for c in subs[:5])
            deliver(f"📦 {name}: {len(subs)} {where}" + (" · ✓ pulled" if pulled else ""), body)

    if mode == "--report":
        print(f"# Repo activity — {len(lines)} repo(s) under {CODE}")
        for l in sorted(lines):
            print(l)
    else:
        try:
            STATE.write_text(json.dumps(state))
        except Exception:
            pass


if __name__ == "__main__":
    main()
