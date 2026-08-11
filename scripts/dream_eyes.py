#!/usr/bin/env python3
"""What the owner actually SAID — the evidence half of `nb dream`.

`nb writeback` already mines the same transcripts, but for what the agents
DID: files edited, tools used, commits landed. AGENTS.md says the limit out
loud — "the auto note records what happened, not what it means." What it means
is in the owner's own turns, and nothing has ever read those: summarize() keeps
first_user[:400], recall.py indexes assistant turns only.

So this reads user turns and hands them to the model as quotable evidence.
Everything here is a filter, and the filters ARE the feature — 3% of raw user
turns survive. The rest is hook injections, slash commands, pasted stack
traces, and nathanbot's own prompts talking to itself. A pass that mined those
would learn a model of its own boilerplate and call it a model of the owner.

Read-only. No AI, no writes, no network. `nb dream --show` is this file.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import transcripts as T  # noqa: E402

ROOT = T.ROOT
STAMP = os.path.join(ROOT, "tasks", "state", "dream.last")
OVERVIEW = os.path.join(ROOT, "shared-memory", "OVERVIEW.md")

# Hook- and harness-injected blocks. These arrive as type:"user" records
# because that is how the CLI feeds them to the model, but the owner did not type
# a word of them, and they are the single largest source of noise.
_HOOKY = re.compile(
    r"^\s*<(local-command-caveat|command-name|command-message|command-args"
    r"|local-command-stdout|local-command-stderr|task-notification|task-id"
    r"|system-reminder|tool-use-id|output-file|user-prompt-submit-hook)\b")
_SLASH = re.compile(r"^\s*/[a-z][\w:.-]*(\s|$)")
_NOISE = re.compile(r"^\s*(\[Request interrupted|\[Tool )")
_CODEY = re.compile(
    r"^\s*(```|~~~|\{|\[|<\?xml|<!DOCTYPE|<html|import\s|from\s+[\w.]+\s+import"
    r"|def\s|class\s|function\s|const\s|export\s|SELECT\s|Traceback \(most recent"
    r"|diff --git|\+\+\+ |--- |commit [0-9a-f]{7})", re.I)
# Turns where the owner was quoting a page AT an agent. Cheap to drop, and a
# memory line sourced from one is not worth the risk. Counted, never silent.
_INJECT = re.compile(
    r"(ignore (all |the )?(previous|prior|above)|disregard (the )?(above|previous)"
    r"|you (are|must) now\b|system prompt|new instructions?:"
    r"|write (this )?to (the )?file|append the following to)", re.I)

MIN_CHARS = 25          # "shorter and better" survives; "ok" does not
MAX_CHARS = 1200        # per turn
MAX_LINES = 12          # more than this is a paste, not a sentence
PER_SESSION = 12        # newest-first within one session
DEFAULT_TOTAL = int(os.environ.get("NB_DREAM_MAX_CHARS", "24000"))
CLAMP_DAYS = 7          # a month-long gap must not produce a month of evidence


def _local(ts):
    """ISO-8601 from a transcript -> aware local datetime, or None."""
    if not ts:
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone()


def _stamp_date():
    """The last satisfied dream occurrence, as a local date. rundue.sh writes
    this in ISO-8601 LOCAL (lastdue.py), so no timezone maths is needed."""
    try:
        with open(STAMP) as fh:
            return datetime.fromisoformat(fh.read().strip()).date()
    except Exception:
        return None


def window(args):
    """(lo_date, hi_date) inclusive, both local.

    rundue.sh fires a missed job ONCE, not once per missed day, so a pass keyed
    on `date +%F` silently drops a weekend the Mac was off. The left edge is the
    last satisfied occurrence instead — clamped, because a month-long gap should
    not produce a month of memory lines.
    """
    today = datetime.now().astimezone().date()
    if args.day:
        d = datetime.strptime(args.day, "%Y-%m-%d").date()
        return d, d
    if args.since:
        return datetime.fromisoformat(args.since).date(), today
    if args.days:
        return today - timedelta(days=args.days - 1), today
    lo = _stamp_date() or (today - timedelta(days=1))
    floor = today - timedelta(days=CLAMP_DAYS - 1)
    return max(lo, floor), today


def keep_session(s):
    """Why a whole session never gets read.

    sdk-cli is the one that matters: every `claude -p` through bin/claudew lands
    there, so its user turns are nathanbot's own prompts. Mining them teaches
    the system its own prompt text as the owner's preferences — the exact failure
    bin/claudew forbids for telemetry, arrived at from the other direction.
    """
    if s["sidechain"]:
        return False, "sidechain"
    if s["entrypoint"] == "sdk-cli":
        return False, "sdk-cli"
    if T.classify(s["first_user"]) != "unknown":
        return False, "headless"
    return True, ""


def keep_turn(r):
    """(keep, drop_reason). Order matters: cheapest and most common first."""
    text = r["text"]
    origin = r["origin"]
    if origin == "human":
        pass
    elif origin is None:
        # Pre-2026-07 transcripts carry no origin marker and are most of the
        # corpus (measured 16403 vs 1697). Missing means unknown, not "not
        # human" — treating it as a drop would blind the pass to its history.
        if r["entrypoint"] == "sdk-cli":
            return False, "sdk-cli"
        if r["prompt_source"] not in (None, "typed", "queued"):
            return False, "not-typed"
    else:
        return False, "not-human"          # task-notification and friends

    head = text[:200]
    if _HOOKY.match(head) or "<system-reminder>" in text:
        return False, "hook"
    if _SLASH.match(head) or _NOISE.match(head):
        return False, "command"
    stripped = text.strip()
    if len(stripped) < MIN_CHARS:
        return False, "short"
    if _CODEY.match(head):
        return False, "paste"
    if len(text) > MAX_CHARS or text.count("\n") + 1 > MAX_LINES:
        return False, "paste"
    if _INJECT.search(text):
        return False, "injection-shaped"
    return True, ""


def _key(text):
    return re.sub(r"\W+", " ", text.lower()).strip()[:200]


def collect(lo, hi):
    """Every surviving turn in the window, plus a tally of what was dropped."""
    since = datetime.combine(lo, datetime.min.time()).astimezone() - timedelta(days=1)
    dropped = defaultdict(int)
    by_session = defaultdict(list)
    projects = {}
    sessions_read = 0

    for path, _mt in T.iter_transcripts(since.timestamp()):
        s = T.summarize(path)
        ok, why = keep_session(s)
        if not ok:
            dropped[why] += 1
            continue
        sessions_read += 1
        sid = s["session"][:8]
        projects[sid] = os.path.basename(s["cwd"]) or "-"
        for r in T.user_turns(path):
            when = _local(r["ts"])
            if not when or not (lo <= when.date() <= hi):
                continue
            ok, why = keep_turn(r)
            if not ok:
                dropped[why] += 1
                continue
            by_session[sid].append({"day": when.date().isoformat(),
                                    "time": when.strftime("%H:%M"),
                                    "sid": sid,
                                    "project": projects[sid],
                                    "text": r["text"].strip()})

    # Per-session cap, newest first: a single long session must not crowd out
    # every other day in the window.
    turns = []
    for sid, rows in by_session.items():
        rows.sort(key=lambda x: (x["day"], x["time"]))
        if len(rows) > PER_SESSION:
            dropped["over-cap"] += len(rows) - PER_SESSION
            rows = rows[-PER_SESSION:]
        turns.extend(rows)

    # Global dedupe, keeping the earliest occurrence.
    turns.sort(key=lambda x: (x["day"], x["time"], x["sid"]))
    seen, unique = set(), []
    for t in turns:
        k = _key(t["text"])
        if k in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(k)
        unique.append(t)
    return unique, dropped, sessions_read


def budget(turns, total):
    """Drop oldest days first until the block fits. Recent words matter more,
    and a truncation nobody is told about reads as 'that was everything'."""
    cut = 0
    while turns and sum(len(t["text"]) + 40 for t in turns) > total:
        oldest = turns[0]["day"]
        keep = [t for t in turns if t["day"] != oldest]
        if not keep:
            turns = turns[-1:]
            break
        cut += len(turns) - len(keep)
        turns = keep
    return turns, cut


def render(turns, dropped, lo, hi, sessions_read, cut):
    out = []
    span = lo.isoformat() if lo == hi else f"{lo} .. {hi}"
    sids = {t["sid"] for t in turns}
    out.append(f"# what the owner actually said — {span}")
    out.append(f"# {len(turns)} turns from {len(sids)} sessions "
               f"({sessions_read} sessions read).")
    if dropped:
        detail = ", ".join(f"{v} {k}" for k, v in sorted(dropped.items(),
                                                         key=lambda kv: -kv[1]))
        out.append(f"# dropped: {detail}.")
    if cut:
        out.append(f"# {cut} turns cut from the oldest days to fit the size budget.")
    try:
        n = os.path.getsize(OVERVIEW)
        out.append(f"# budget: shared-memory/OVERVIEW.md is {n} chars "
                   f"(target ~2000, nb audit warns at 2600).")
    except OSError:
        pass
    out.append("# NOTE: the project label comes from a session's cwd, which for "
               "desktop sessions")
    out.append("# is often just ~/Projects. Route a fact by what it SAYS, never "
               "by this label.")
    out.append("")

    day = None
    for t in turns:
        if t["day"] != day:
            day = t["day"]
            out.append(f"## {day}")
        body = " ".join(t["text"].split())
        out.append(f'- [{t["sid"]} {t["time"]}] [{t["project"]}] "{body}"')
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="user turns worth remembering")
    ap.add_argument("--since", help="ISO date; overrides the dream.last stamp")
    ap.add_argument("--days", type=int, help="last N days, today inclusive")
    ap.add_argument("--day", help="one specific day, YYYY-MM-DD")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_TOTAL)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--window", action="store_true",
                    help="print the resolved window as 'lo hi' and exit")
    args = ap.parse_args()

    lo, hi = window(args)
    if args.window:
        print(f"{lo} {hi}")
        return 0

    turns, dropped, sessions_read = collect(lo, hi)
    turns, cut = budget(turns, args.max_chars)

    if args.json:
        print(json.dumps({"lo": lo.isoformat(), "hi": hi.isoformat(),
                          "turns": turns, "dropped": dict(dropped),
                          "sessions_read": sessions_read, "cut": cut},
                         indent=2))
        return 0

    # No turns means write nothing. The caller checks for empty stdout, so the
    # header must not be printed here — a header alone would read as evidence.
    if not turns:
        return 0
    print(render(turns, dropped, lo, hi, sessions_read, cut))
    return 0


if __name__ == "__main__":
    sys.exit(main())
