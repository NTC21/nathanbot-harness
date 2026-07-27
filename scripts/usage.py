#!/usr/bin/env python3
"""nb usage — what the agents actually did, in dollars and tool calls.

  usage.py [--days N] [--all] [--job X] [--sessions]

Reads the CLI's own transcripts (see scripts/lib/transcripts.py). Nothing is
instrumented and nothing is written, so this works retroactively over history
that already exists.

Costs are LIST-PRICE EQUIVALENT, not billed spend — the owner is on a subscription.
The number answers "what is this worth / where is it going", not "what was I
charged".

The metric that justifies the whole thing is `empty`: runs that completed with
zero tool calls and almost no output. That is the mechanical form of "this
scheduled job ran and did nothing", which went unnoticed for five days.
"""
import argparse
import json
import subprocess
import os
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/lib")
import transcripts as T  # noqa: E402

B, D, G, Y, R_, X = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"

CACHE = os.path.join(T.ROOT, "tasks", ".usage-cache.json")
EMPTY_OUT_TOKENS = 200      # below this AND zero tools = the job did nothing


def load_cache():
    try:
        return json.load(open(CACHE))
    except Exception:
        return {}


def money(x):
    return f"${x:,.2f}" if x >= 0.005 else f"${x:.3f}"


def digest(day):
    """Structured evidence of one day's agent work, for the write-back pass.

    Reads what actually happened — files edited, commands run, which job, which
    project — rather than asking a model to recall its own session. That is the
    same distinction learn.sh draws ("what he actually did, not what he said"),
    and it is the only version that cannot quietly not happen.

    Prints nothing at all for a day with no sessions. The caller must treat empty
    as "write nothing": a "quiet day" note would be a report that cannot fail.
    """
    import datetime
    day = day or datetime.date.today().isoformat()
    lo = datetime.datetime.fromisoformat(day).timestamp()
    labels = T.trace_labels()
    by_project = defaultdict(list)

    for path, mt in T.iter_transcripts(lo - 86400):
        s = T.summarize(path)
        if s.get("sidechain") or not s.get("first_ts", "").startswith(day):
            continue
        proj = os.path.basename(s.get("cwd") or "") or "(no project)"
        job = labels.get(s["session"], {}).get("job") or T.classify(s.get("first_user", ""))
        if s.get("entrypoint") != "sdk-cli" and job in ("unknown", "operator"):
            job = "interactive"
        files = sorted(set(os.path.relpath(f, s["cwd"]) if s.get("cwd") and f.startswith(s["cwd"])
                           else f for f in s["files"]))
        if not files and sum(s["tools"].values()) == 0:
            continue                      # nothing happened; nothing to say
        by_project[proj].append({
            "job": job, "session": s["session"][:8],
            "tools": dict(s["tools"]), "files": files[:25],
            "agents": [t for t, _ in T.subagents(path)],
        })

    if not by_project:
        return 0                          # prints nothing — caller writes nothing

    print(f"# agent activity for {day}")
    for proj, sessions in sorted(by_project.items()):
        print(f"\n## {proj}")
        for s in sessions:
            tools = ", ".join(f"{k}x{v}" for k, v in
                              sorted(s["tools"].items(), key=lambda kv: -kv[1])[:6])
            print(f"- {s['job']} [{s['session']}] — {tools or 'no tools'}")
            if s["agents"]:
                print(f"    dispatched: {', '.join(s['agents'])}")
            for f in s["files"]:
                print(f"    edited: {f}")
        # commits in that repo, that day — the other half of "what happened"
        for base in (os.path.expanduser(f"~/Projects/{proj}"), proj):
            if os.path.isdir(os.path.join(base, ".git")):
                try:
                    log = subprocess.run(
                        ["git", "-C", base, "log", "--since", day, "--until",
                         f"{day} 23:59:59", "--format=- commit: %s"],
                        capture_output=True, text=True, timeout=20).stdout.strip()
                    if log:
                        print(log)
                except Exception:
                    pass
                break
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true", help="every transcript ever")
    ap.add_argument("--job", help="only this job label")
    ap.add_argument("--sessions", action="store_true", help="list each run")
    ap.add_argument("--digest", action="store_true",
                    help="structured evidence for one day (feeds writeback.sh)")
    ap.add_argument("--day", help="YYYY-MM-DD, with --digest")
    a = ap.parse_args()

    if a.digest:
        return digest(a.day)

    prices = T.price_table()
    labels = T.trace_labels()
    since = None if a.all else time.time() - a.days * 86400
    cache, dirty = load_cache(), False

    runs, tools, by_job, by_model = [], Counter(), defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0])
    unpriced, agents = set(), Counter()
    tot = tin = tout = tcache = 0.0
    n_unpriced_runs = 0

    for path, mt in T.iter_transcripts(since):
        key = f"{path}:{int(mt)}:{os.path.getsize(path)}"
        s = cache.get(key)
        if s is None:
            raw = T.summarize(path)
            # Counters don't survive JSON; store plain dicts.
            s = {**raw, "models": dict(raw["models"]), "tools": dict(raw["tools"]),
                 "usage": {m: dict(c) for m, c in raw["usage"].items()},
                 "subagents": [t for t, _ in T.subagents(path)]}
            cache[key] = s
            dirty = True
        if s.get("sidechain"):
            continue                      # subagent transcripts; counted via the parent

        lab = labels.get(s["session"], {})
        # entrypoint separates nathanbot's own agents (sdk-cli, i.e. claude -p)
        # from the owner sitting in Claude Code. Both are real spend, but mixing
        # them buries the thing this report exists to show: whether the
        # unattended half of the system is doing anything.
        headless = s.get("entrypoint") == "sdk-cli"
        job = lab.get("job") or T.classify(s.get("first_user", ""))
        if not headless and job in ("unknown", "operator"):
            job = "interactive"
        if a.job and job != a.job:
            continue

        rebuilt = {**s, "usage": {m: Counter(c) for m, c in s["usage"].items()}}
        cost, up = T.session_cost(rebuilt, prices)
        unpriced |= up
        if cost is None:
            n_unpriced_runs += 1
            cost = 0.0

        for m, c in s["models"].items():
            by_model[m][1] += 1
        for m, u in s["usage"].items():
            mc = T.cost_of(m, {"input_tokens": u["input_tokens"],
                               "output_tokens": u["output_tokens"],
                               "cache_read_input_tokens": u["cache_read_input_tokens"],
                               "cache_creation": {"ephemeral_5m_input_tokens": u.get("w5", 0),
                                                  "ephemeral_1h_input_tokens": u.get("w1", 0)},
                               "cache_creation_input_tokens": u["cache_creation_input_tokens"]},
                          prices)
            if mc:
                by_model[m][0] += mc
            tin += u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"]
            tout += u["output_tokens"]
            tcache += u["cache_read_input_tokens"]

        tot += cost
        by_job[job][0] += cost
        by_job[job][1] += 1
        tools.update(s["tools"])
        for at in s.get("subagents", []):
            agents[at] += 1
        runs.append({"job": job, "cost": cost, "ts": s.get("first_ts", "")[:16],
                     "tools": sum(s["tools"].values()), "out": s.get("out_tokens", 0),
                     "killed": lab.get("killed"), "traced": bool(lab),
                     "cwd": s.get("cwd", ""), "session": s["session"],
                     "headless": headless})

    if dirty:
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            json.dump(cache, open(CACHE, "w"))
        except OSError:
            pass

    if not runs:
        print(f"{D}no agent runs in the last {a.days}d{X}")
        return 0

    span = "all time" if a.all else f"{a.days}d"
    print(f"\n{B}Usage — {span}{X}  {D}list-price equivalent; you're on a subscription, "
          f"this is not billed spend{X}")

    if prices:
        head = f"  {B}{money(tot)}{X}"
    else:
        head = f"  {R_}cost unavailable{X} {D}(could not read the CLI price table){X}"
    hit = (tcache / tin * 100) if tin else 0
    print(f"{head} · {len(runs)} runs · {tin/1e6:.1f}M in / {tout/1e3:.0f}K out "
          f"· cache read {hit:.0f}%")

    def row(label, items, n=6):
        # Without a price table these are all 0.0, and printing "$0.000" reads as
        # a measured zero rather than a missing measurement. Show counts instead,
        # ranked by run count, and let the header carry the reason.
        if prices:
            ranked = sorted(items.items(), key=lambda kv: -kv[1][0])[:n]
            parts = [f"{k} {money(v[0])} ({v[1]})" for k, v in ranked]
        else:
            ranked = sorted(items.items(), key=lambda kv: -kv[1][1])[:n]
            parts = [f"{k} ({v[1]})" for k, v in ranked]
        if parts:
            print(f"  {D}{label:8}{X}" + " · ".join(parts))

    row("job", by_job)
    row("model", by_model)
    if tools:
        print(f"  {D}{'tools':8}{X}" + " · ".join(f"{k} {v}" for k, v in tools.most_common(8)))
    print(f"  {D}{'agents':8}{X}" + (" · ".join(f"{k} {v}" for k, v in agents.most_common())
                                     if agents else f"{Y}none dispatched{X}"))

    # the metric this exists for
    # Scoped to unattended jobs on purpose. A chat reply with no tool call is
    # normal — the operator is told to answer in 1-3 lines — so counting those
    # would make the metric fire constantly and get ignored, which is the exact
    # failure mode of a check that cannot mean anything.
    empty = [r for r in runs if r["tools"] == 0 and r["out"] < EMPTY_OUT_TOKENS
             and r["job"] not in ("interactive", "operator", "discuss")]
    if empty:
        c = Counter(r["job"] for r in empty)
        print(f"  {Y}{'empty':8}{X}" + " · ".join(f"{k} ×{v}" for k, v in c.most_common())
              + f"  {D}(ran, zero tool calls, <{EMPTY_OUT_TOKENS} output tokens){X}")

    killed = [r for r in runs if r["killed"]]
    if killed:
        cost_note = (f"{money(sum(r['cost'] for r in killed))} spent with no result returned"
                     if prices else "cost unknown — no price table")
        print(f"  {Y}{'killed':8}{X}{len(killed)} run(s) timed out — {cost_note}")
    if unpriced:
        print(f"  {R_}{'unpriced':8}{X}{n_unpriced_runs} run(s) on {', '.join(sorted(unpriced))}"
              f" — NOT counted above")
    stray = [r for r in runs if r["cwd"] == "/"]
    if stray:
        print(f"  {Y}{'no cwd':8}{X}{len(stray)} run(s) at '/' — no agents, no CLAUDE.md")

    if a.sessions:
        print()
        for r in sorted(runs, key=lambda r: r["ts"], reverse=True)[:30]:
            flag = f" {Y}killed{X}" if r["killed"] else ""
            print(f"  {r['ts']}  {r['job']:10} {money(r['cost']):>8}  "
                  f"{r['tools']:3} tools{flag}  {D}{r['session'][:8]}{X}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
