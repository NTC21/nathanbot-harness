#!/usr/bin/env python3
"""telemetry.py — read tasks/.telemetry.jsonl and say what a non-zero exit MEANT.

usage.py reads the Claude CLI's transcripts; this is the other half of the record
— every `nb <verb>` invocation, including the ones that never called an agent.
`rc` has been written on every line since 2026-07-21 and read by nothing, so
`nb usage` could not answer the question it was being run to answer.

The honest part is SCHEMA_V. Lines written before the labelling landed carry no
"v" key, and their non-zero exits genuinely cannot be told apart. They report as
one `unclassified` bucket rather than being sorted by a command-name list — a
list like that drifts out of date the moment a command changes behaviour, which
is precisely the class of bug this system keeps finding in itself.

Shared by `nb usage` and `scripts/audit.sh` so the two never disagree about what
counts as a failure.
"""
import json
import os
import datetime

SCHEMA_V = 2

# rc 126 = found but not executable · 127 = not found · 128+n = killed by signal n
_SHELL = {126: "unrunnable", 127: "unrunnable"}
_SIGNAL_MIN = 128          # 130 Ctrl-C · 141 SIGPIPE · 143 SIGTERM
# argparse's own exit code for a bad invocation. Everything `nb` dispatches to is
# either an argparse script or agrees with it by hand (scripts/wiki.sh, and
# _usage() in scripts/google/gcalendar.py). scripts/release-public.sh also exits
# 2 on a real failure, but it is not reachable through `nb`, so it never reaches
# this file -- check that before wiring a new caller that uses 2 to mean broken.
_USAGE = 2


def classify(row):
    """None if the run succeeded, else the name of a failure class."""
    rc = row.get("rc")
    if rc in (0, None):
        return None
    if row.get("v", 0) < SCHEMA_V:
        return "unclassified"
    means = row.get("rc_means")
    if means:
        return means                      # finding | unknown-verb | retired | skipped
    if rc == _USAGE:
        # The command ran and rejected the invocation: a missing --account, an
        # unparseable flag. Nothing is broken, so counting it as a failure makes
        # the number climb every time a verb is typed wrong -- and a count that
        # rises when nothing is wrong is one that gets ignored, which is the
        # whole reason this module exists. Checked BEFORE _SHELL so the meaning
        # is stated once here rather than at 19 `die` sites.
        return "usage"
    if rc in _SHELL:
        return _SHELL[rc]
    if rc >= _SIGNAL_MIN:
        # any 128+n, not just the three we happened to have seen. `nb next | head`
        # dies of SIGPIPE (141) and would otherwise report as a crash -- and
        # piping nb into head or grep is something the owner does constantly, so
        # that alone would make audit section 15 fire on nothing and get ignored.
        return "interrupted"
    return "crashed"


# (short label, why it is not — or is — a failure)
LABEL = {
    "crashed":      ("crashed", "exited non-zero with no reason recorded"),
    "unrunnable":   ("unrunnable", "found but could not execute"),
    "unknown-verb": ("no such verb", "a typo, or a command that was removed"),
    "interrupted":  ("interrupted", "killed by a signal — Ctrl-C, SIGTERM, or a closed pipe"),
    "retired":      ("retired", "the command exists only to say it is gone"),
    "skipped":      ("stood down", "another pass held the lock — nothing lost"),
    "finding":      ("found", "non-zero on purpose — it found something"),
    "usage":        ("bad invocation", "the command ran and rejected the arguments"),
    "unclassified": ("unclassified", "logged before exits were labelled"),
}

# What audit.sh treats as an actual problem. Deliberately narrow: counting
# `finding` here would make the check fire on ~22 correct runs and get ignored,
# which is the failure mode audit.sh already names about itself.
REAL_FAILURES = ("crashed", "unrunnable")

# Worst first, so the report leads with what matters.
ORDER = ("crashed", "unrunnable", "unknown-verb", "usage", "interrupted",
         "retired", "skipped", "finding", "unclassified")


def _epoch(ts):
    try:
        return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        return None


def rows(path, since=None):
    """Every parseable line, optionally only those newer than `since` (epoch).

    Malformed lines are skipped rather than raising: audit.sh section 10 already
    reports on those, and a reader that dies on one bad line is a reader that
    stops reporting entirely.
    """
    if not os.path.exists(path):
        return []
    out = []
    with open(path, errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if since is not None:
                e = _epoch(r.get("ts", ""))
                if e is None or e < since:
                    continue
            out.append(r)
    return out


def label_of(row):
    """The key a failure is counted under: `cmd`, or `cmd sub` when recorded."""
    cmd = row.get("cmd", "?")
    sub = row.get("sub")
    return f"{cmd} {sub}" if sub else cmd


def tally(rows_):
    """-> ({class: {label: count}}, (earliest_ts, latest_ts) of unclassified)."""
    buckets, lo, hi = {}, None, None
    for r in rows_:
        k = classify(r)
        if not k:
            continue
        buckets.setdefault(k, {})
        lbl = label_of(r)
        buckets[k][lbl] = buckets[k].get(lbl, 0) + 1
        if k == "unclassified":
            ts = (r.get("ts") or "")[:10]
            if ts:
                lo = ts if lo is None or ts < lo else lo
                hi = ts if hi is None or ts > hi else hi
    return buckets, (lo, hi)


def count(buckets, classes):
    return sum(sum(c.values()) for k, c in buckets.items() if k in classes)
