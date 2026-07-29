#!/usr/bin/env python3
"""asks.py — the question a task is waiting on, in words the owner can act on.

The brief used to say "t-0027 is blocked". The useful sentence is the one inside
the task: "which Google account owns you@your-business.com?" the owner's constraint,
verbatim: "make it plain English so I don't waste time trying to figure out what
the question is."

So the question is resolved in three steps, best first:

  1. the `ask:` frontmatter field — one plain-English line, written by whoever
     created the task. A contract, not a guess. TASK_STYLE (bin/nb) tells every
     generator to fill it.
  2. the body's "**What I need from you**" section, condensed. Works on the tasks
     that already exist, but no regex can GUARANTEE it lands on the question.
  3. the title. Always something, never nothing.

Two statuses count as waiting on the owner:
  needs-decision — an explicit question
  proposed       — an AI suggestion he has never looked at. There are currently
                   ZERO needs-decision tasks and four `proposed` ones aged 4-5
                   days, so leaving `proposed` out would leave the chaser with
                   nothing to chase.

  asks.py --tsv        id \\t age \\t status \\t short-question \\t title
  asks.py --md         the markdown block for the brief file (full text)
  asks.py --telegram   only what is due a phone ping; stamps tasks/state/chased.json
  asks.py --all        every open task + what was extracted (the test harness)

Knobs: NB_CHASE_DAYS (default 2), NB_CHASE_REPING_DAYS (default 7), and a
per-task `chase: off` frontmatter field, mirroring stale.py's `stale-check: off`.
NB_BRIEF_DRYRUN=1 makes --telegram print without stamping.
"""
import datetime
import json
import os
import pathlib
import re
import sys

R = pathlib.Path(__file__).resolve().parents[2]
OPEN = R / "tasks" / "open"
STATE = R / "tasks" / "state" / "chased.json"

WAITING = ("needs-decision", "proposed")
CHASE_DAYS = int(os.environ.get("NB_CHASE_DAYS", "2"))
REPING_DAYS = int(os.environ.get("NB_CHASE_REPING_DAYS", "7"))
SHORT_LIMIT = 160          # keeps the spoken brief inside speak.sh's NB_SPEAK_MAX

_FM = re.compile(r"\A---\n(.*?)\n---", re.S)
_HEAD = re.compile(r"^\*\*What I need from you\*\*(?:\s*[—–-]\s*)?(.*)$", re.M)
# where the section ends: the next bolded section, the technical footer, or a rule
_STOP = re.compile(r"^(\*\*(?:What|Why|Done when|Blocked)|\*Technical:|\*Blocked by:|---\s*$)")
# split on sentence end, but not inside "(X? LinkedIn? YouTube?)"
_SPLIT = re.compile(r'(?<=[.?!:])\s+(?=[A-Z"“])')


def frontmatter(text):
    fm, m = {}, _FM.search(text)
    if not m:
        return fm
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def section(text):
    """The verbatim '**What I need from you**' block, or None."""
    m = _HEAD.search(text)
    if not m:
        return None
    lines = [m.group(1).strip()] if m.group(1).strip() else []
    for line in text[m.end():].splitlines():
        if _STOP.match(line):
            break
        lines.append(line)
    body = "\n".join(lines).strip()
    return body or None


def short(sec, limit=SHORT_LIMIT):
    """Condense a section to one readable line.

    These tasks put the setup first and the ask last, so when the opening
    paragraph is too long the first+last sentence pair carries more meaning than
    a head truncation does. t-0027 is the case that proves it.
    """
    if not sec:
        return None
    para = ""
    for block in re.split(r"\n\s*\n", sec):
        b = " ".join(x.strip() for x in block.splitlines()).strip()
        if b and not b.lstrip().startswith(("-", "*", "•")):
            para = b
            break
    if not para:
        para = " ".join(x.strip().lstrip("-*• ") for x in sec.splitlines() if x.strip())
    para = re.sub(r"\s+", " ", para).strip()
    if len(para) <= limit:
        return para
    parts = [p.strip() for p in _SPLIT.split(para) if p.strip()]
    if len(parts) > 1:
        combo = f"{parts[0]} … {parts[-1]}"
        if len(combo) <= limit:
            return combo
    cut = para[:limit]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 40 else cut).rstrip(" ,;:") + " …"


def age_days(created):
    try:
        d = datetime.date.fromisoformat(created)
    except Exception:
        return 0
    return (datetime.date.today() - d).days


def collect(all_tasks=False):
    out = []
    for f in sorted(OPEN.glob("*.md")):
        text = f.read_text(errors="replace")
        fm = frontmatter(text)
        st = fm.get("status", "")
        waiting = st in WAITING
        if not all_tasks:
            if not waiting or fm.get("chase", "").lower() == "off":
                continue
        age = age_days(fm.get("created", ""))
        sec = section(text)
        explicit = fm.get("ask") or None
        q = explicit or short(sec) or fm.get("title", f.stem)
        out.append({
            "id": fm.get("id", f.stem.split("-")[0]),
            "title": fm.get("title", f.stem),
            "status": st, "age": age, "q": q, "section": sec,
            "source": "ask:" if explicit else ("body" if sec else "title"),
            "overdue": waiting and age >= CHASE_DAYS
                       and fm.get("chase", "").lower() != "off",
        })
    out.sort(key=lambda r: (-r["age"], r["id"]))
    return out


def _load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save_state(d):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, indent=1))
    except OSError:
        pass


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--tsv"

    if mode == "--all":
        for r in collect(all_tasks=True):
            mark = "CHASE" if r["overdue"] else ("wait" if r["status"] in WAITING else "-")
            print(f"{r['id']}  {r['age']:>3}d  {r['status']:<14} {mark:<5} "
                  f"[{r['source']}] {r['q']}")
        return 0

    rows = [r for r in collect() if r["overdue"]]
    if not rows:
        return 0

    if mode == "--tsv":
        for r in rows:
            print("\t".join([r["id"], str(r["age"]), r["status"], r["q"], r["title"]]))
        return 0

    if mode == "--md":
        print("## Answer these")
        print()
        for r in rows:
            print(f"### {r['id']} — waiting {r['age']} days")
            print(f"*{r['title']}*")
            print()
            # The `ask:` line LEADS, then the body section as supporting detail.
            # The other order buries it -- and worse, goes stale: t-0027's body
            # still poses the original three-way question after the answer was
            # given, because the answer was appended further down the file.
            if r["source"] == "ask:":
                print(f"**{r['q']}**")
                if r["section"]:
                    print()
                    print("<details><summary>background</summary>")
                    print()
                    print(r["section"])
                    print()
                    print("</details>")
            else:
                print(r["section"] or r["q"])
            print()
            print(f"→ `nb decide {r['id']}` to approve, defer or drop")
            print()
        return 0

    if mode == "--telegram":
        # the owner chose: brief every morning, Telegram rarely. First ping when a
        # question crosses NB_CHASE_DAYS, then at most once a week after that.
        # Without the stamp file this would ping daily and be muted within a week,
        # which is how a chaser stops working while still appearing to run.
        state = _load_state()
        today = datetime.date.today()
        due, fresh = [], dict(state)
        for r in rows:
            last = state.get(r["id"])
            if last:
                try:
                    if (today - datetime.date.fromisoformat(last)).days < REPING_DAYS:
                        continue
                except Exception:
                    pass
            due.append(r)
            fresh[r["id"]] = today.isoformat()
        if not due:
            return 0
        for r in due:
            print(f"• {r['id']} ({r['age']} days) — {r['q']}")
        if not os.environ.get("NB_BRIEF_DRYRUN"):
            # prune ids that are no longer waiting, so a reopened task pings again
            live = {r["id"] for r in collect() if r["overdue"]}
            _save_state({k: v for k, v in fresh.items() if k in live})
        return 0

    print(f"unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
