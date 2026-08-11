#!/usr/bin/env python3
"""Calendar for nathanbot. --account is ALWAYS required (except 'agenda --all').

Design informed by OpenJarvis's gcalendar connector (github.com/open-jarvis/OpenJarvis,
Apache-2.0), reimplemented on nathanbot's google-api-python-client stack + auth.py.

  calendar.py --account <k> agenda [--days N]         upcoming, one account
  calendar.py agenda --all [--days N]                 merged across ALL authorized accounts
  calendar.py --account <k> list [--days N]
  calendar.py --account <k> search "<text>" [--days N]
  calendar.py --account <k> create --title "<t>" --start <ISO> --end <ISO> [--attendees a,b --yes <k>]
  calendar.py --account <k> respond <event-id> --status accepted|declined|tentative --yes <k>

Outward-facing actions (inviting attendees, RSVPing) require --yes <account-key>,
exactly like gmail send — they leave the account and are visible to others.
"""
import argparse, sys, os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auth  # noqa: E402


def _usage(msg):
    """Bad invocation -- exit 2, the code argparse itself uses for this.

    `sys.exit(msg)` exits 1, and scripts/lib/telemetry.py cannot tell a 1 that
    means "you forgot --account" from a 1 that means a traceback. Everything
    reachable through `nb` treats 2 as a usage error (scripts/wiki.sh already
    did), so hand-rolled argument checks must agree with argparse rather than
    inventing a second convention.
    """
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def unattended():
    """True when nobody is approving actions one by one.

    Mirrors claude-hooks/nb_guard.is_unattended(). These fuses used to read
    NB_OPERATOR alone, so a scheduled job — which sets NB_UNATTENDED and not
    NB_OPERATOR — could write to the calendar with no human in the loop.
    """
    return bool(os.environ.get("NB_OPERATOR") or os.environ.get("NB_UNATTENDED"))


def local_tz():
    """Best-effort IANA timezone name so events don't silently land in UTC."""
    p = os.path.realpath("/etc/localtime")
    return p.split("zoneinfo/")[-1] if "zoneinfo/" in p else "UTC"


def svc(key):
    from googleapiclient.discovery import build
    creds = auth.get_credentials(key)
    return build("calendar", "v3", credentials=creds), auth.expected_email(key)


def _fmt(ev):
    s = ev.get("start", {})
    st = s.get("dateTime", s.get("date", "?"))
    return st, ev.get("summary", "(no title)"), ev.get("location", "")


def _window(days, past=False):
    # past=True looks BACKWARD (now-days .. now) instead of forward. Needed by
    # `nb ideas`, which asks what actually happened today, not what is coming.
    now = datetime.now(timezone.utc)
    if past:
        return (now - timedelta(days=days)).isoformat(), now.isoformat()
    return now.isoformat(), (now + timedelta(days=days)).isoformat()


def list_events(key, days=7, query=None, past=False):
    service, email = svc(key)
    tmin, tmax = _window(days, past)
    kw = dict(calendarId="primary", timeMin=tmin, timeMax=tmax,
              singleEvents=True, orderBy="startTime", maxResults=50)
    if query:
        kw["q"] = query
    return email, service.events().list(**kw).execute().get("items", [])


def _print_rows(items):
    for ev in items:
        st, title, loc = _fmt(ev)
        print(f"  {st}  {title}" + (f"  @ {loc}" if loc else ""))


def cmd_list(a):
    email, items = list_events(a.account, a.days)
    print(f"# {email} — next {a.days}d ({len(items)} events)")
    _print_rows(items)


def cmd_search(a):
    email, items = list_events(a.account, a.days, a.query)
    print(f"# {email} — '{a.query}' ({len(items)} matches)")
    _print_rows(items)


def cmd_agenda(a):
    keys = list(auth.accounts_cfg()) if a.all else [a.account]
    rows = []
    past = getattr(a, "past", False)
    for k in keys:
        try:
            _email, items = list_events(k, a.days, past=past)
        except SystemExit:
            continue  # account not authorized — skip silently in --all
        except Exception as e:
            print(f"  ({k}: {e})", file=sys.stderr)
            continue
        for ev in items:
            st, title, loc = _fmt(ev)
            rows.append((st, k, title, loc))
    rows.sort(key=lambda r: r[0])
    span = f"last {a.days}d" if past else f"next {a.days}d"
    print(f"# Agenda — {span} — {len(rows)} event(s) across {len(keys)} account(s)")
    for st, k, title, loc in rows:
        print(f"  {st}  [{k}] {title}" + (f"  @ {loc}" if loc else ""))


def cmd_create(a):
    attendees = [x.strip() for x in (a.attendees or "").split(",") if x.strip()]
    # HARD FUSE: writing the calendar is the owner's, never the operator's — even a self-block
    # with no attendees. The operator only STAGES a block via the [[CAL_BLOCK]] marker; the
    # server commits it WITHOUT NB_OPERATOR after the owner taps Approve. (Inviting attendees is
    # additionally outward-facing.) This closes the gap where an attendee-less create wasn't fused.
    if unattended():
        sys.exit("REFUSED — creating calendar events is disabled for the operator.\n"
                 "Stage it as a [[CAL_BLOCK]] marker; the owner taps Approve to commit.")
    if attendees and a.yes != a.account:
        sys.exit("Creating an event WITH attendees sends invitations (outward-facing).\n"
                 f"Re-run with:  --yes {a.account}")
    service, _email = svc(a.account)
    tz = local_tz()
    # Google wants full RFC3339 (with seconds); "2026-07-27T08:00" is rejected 400.
    # Normalize so both manual creates and the Approve-tap block commits (which store
    # HH:MM) are accepted. Preserves any offset if the caller supplied one.
    def _rfc3339(s):
        try:
            return datetime.fromisoformat(s.strip()).isoformat()
        except (ValueError, AttributeError):
            return s
    body = {"summary": a.title,
            "start": {"dateTime": _rfc3339(a.start), "timeZone": tz},
            "end": {"dateTime": _rfc3339(a.end), "timeZone": tz}}
    # optional weekly recurrence — --byday MO,WE,FR (builds a weekly RRULE) or raw --rrule
    rrule = a.rrule
    if a.byday:
        days = ",".join(d.strip().upper()[:2] for d in a.byday.split(",") if d.strip())
        rrule = f"FREQ=WEEKLY;BYDAY={days}"
    if rrule:
        body["recurrence"] = ["RRULE:" + rrule.replace("RRULE:", "")]
    if attendees:
        body["attendees"] = [{"email": x} for x in attendees]
    ev = service.events().insert(
        calendarId="primary", body=body,
        sendUpdates="all" if attendees else "none").execute()
    print(f"created ({tz}): {ev.get('htmlLink')}")
    if attendees:
        print(f"  invited: {', '.join(attendees)}")


def cmd_find(a):
    """Locate the MASTER of a recurring series, which is what update/delete need.

    list_events() passes singleEvents=True, so it expands a series into instances and
    every instance carries a per-occurrence id. Editing one of those changes one day and
    silently leaves the series alone — the failure mode where "I moved it" is true on
    Tuesday and false forever after. This asks for masters instead.
    """
    service, email = svc(a.account)
    tmin, tmax = _window(a.days)
    kw = dict(calendarId="primary", timeMin=tmin, timeMax=tmax,
              singleEvents=False, maxResults=250)
    if a.query:
        kw["q"] = a.query
    items = service.events().list(**kw).execute().get("items", [])
    print(f"# {email} — {'recurring masters + single events'}"
          + (f" matching '{a.query}'" if a.query else "") + f" ({len(items)})")
    for ev in items:
        if ev.get("status") == "cancelled":
            continue
        st, title, _loc = _fmt(ev)
        rec = ev.get("recurrence")
        tag = f"  [{rec[0].replace('RRULE:', '')}]" if rec else ""
        print(f"  {ev['id']}\n      {st}  {title}{tag}")


def _retime(ev, hhmm, minutes):
    """Rewrite only the clock time of an event, preserving its date and timezone.

    A recurring master's start date anchors the whole series, so replacing start/end
    wholesale would move the series' first occurrence and re-phase everything after it.
    Shifting just the time-of-day is what "move Wind Down to 22:30" actually means.
    """
    s = ev.get("start", {}).get("dateTime")
    e = ev.get("end", {}).get("dateTime")
    if not s or not e:
        sys.exit("that event is all-day; --time/--duration only apply to timed events")
    sd = datetime.fromisoformat(s)
    ed = datetime.fromisoformat(e)
    dur = minutes if minutes else int((ed - sd).total_seconds() // 60)
    if hhmm:
        hh, mm = (int(x) for x in hhmm.split(":"))
        sd = sd.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return sd.isoformat(), (sd + timedelta(minutes=dur)).isoformat()


def cmd_update(a):
    # Same hard fuse as create: changing the calendar is the owner's act. An update is if
    # anything worse than a create — a create that lands wrong is visibly extra, whereas
    # a bad update silently overwrites something that was already right.
    if unattended():
        sys.exit("REFUSED — editing calendar events is disabled for the operator.")
    if a.yes != a.account:
        sys.exit(f"Editing an event overwrites what is there. Re-run with:  --yes {a.account}")
    service, _email = svc(a.account)
    ev = service.events().get(calendarId="primary", eventId=a.id).execute()

    body = {}
    if a.title:
        body["summary"] = a.title
    if a.time or a.duration:
        tz = ev.get("start", {}).get("timeZone") or local_tz()
        s, e = _retime(ev, a.time, a.duration)
        body["start"] = {"dateTime": s, "timeZone": tz}
        body["end"] = {"dateTime": e, "timeZone": tz}
    if a.byday and a.clear_recurrence:
        sys.exit("--byday and --clear-recurrence contradict each other")
    if a.byday:
        days = ",".join(d.strip().upper()[:2] for d in a.byday.split(",") if d.strip())
        body["recurrence"] = [f"RRULE:FREQ=WEEKLY;BYDAY={days}"]
    if a.clear_recurrence:
        # Needed to UNDO a --byday. patch() ignores a key that is absent, so there was no way
        # to demote a series back to a single event without this — the only escape was delete
        # plus re-create, which loses the id and any history hanging off it.
        body["recurrence"] = None
    if not body:
        sys.exit("nothing to change — pass --title, --time, --duration, --byday or --clear-recurrence")

    was_st, was_title, _ = _fmt(ev)
    out = service.events().patch(
        calendarId="primary", eventId=a.id, body=body, sendUpdates="none").execute()
    new_st, new_title, _ = _fmt(out)
    print(f"updated: {was_title}  {was_st}\n     ->  {new_title}  {new_st}")
    if out.get("recurrence"):
        print(f"     rrule: {out['recurrence'][0].replace('RRULE:', '')}")
    print(f"     {out.get('htmlLink')}")


def cmd_delete(a):
    # Deleting a recurring master removes every past and future occurrence, and Google
    # offers no undo through the API. Fused and account-restating like the rest.
    if unattended():
        sys.exit("REFUSED — deleting calendar events is disabled for the operator.")
    if a.yes != a.account:
        sys.exit(f"Deleting removes every occurrence and cannot be undone. Re-run with:  --yes {a.account}")
    service, _email = svc(a.account)
    ev = service.events().get(calendarId="primary", eventId=a.id).execute()
    st, title, _ = _fmt(ev)
    service.events().delete(calendarId="primary", eventId=a.id, sendUpdates="none").execute()
    print(f"deleted: {title}  ({st})" + ("  [whole series]" if ev.get("recurrence") else ""))


def cmd_respond(a):
    if unattended():
        sys.exit("REFUSED — RSVPs are visible to the organizer; disabled for the operator.")
    if a.yes != a.account:
        sys.exit(f"An RSVP is visible to the organizer. Re-run with:  --yes {a.account}")
    service, email = svc(a.account)
    ev = service.events().get(calendarId="primary", eventId=a.id).execute()
    hit = False
    for att in ev.get("attendees", []):
        if att.get("self") or att.get("email", "").lower() == email.lower():
            att["responseStatus"] = a.status
            hit = True
    if not hit:
        sys.exit("you are not an attendee on that event")
    service.events().patch(calendarId="primary", eventId=a.id,
                           body={"attendees": ev["attendees"]}, sendUpdates="all").execute()
    print(f"RSVP {a.status}: {ev.get('summary', '(event)')}")


# ── time-blocking: turn today's ready tasks into calendar blocks ─────────────
def _planning_cfg():
    """Planning defaults from config/planning.json. Read from disk so EVERY context
    (brief, operator subprocess, interactive) sees the same window with no env plumbing.
    Env vars still override per-invocation."""
    import json
    try:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        with open(os.path.join(root, "config", "planning.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _work_window():
    """(now, work_start, work_end, tzinfo) — all timezone-aware, today, local.
    Precedence: env var > config/planning.json > hardcoded default."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(local_tz())
    now = datetime.now(tz)
    cfg = _planning_cfg()

    def at(hhmm):
        h, m = (int(x) for x in hhmm.split(":"))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)
    ws = os.environ.get("NB_WORK_START") or cfg.get("work_start") or "09:00"
    we = os.environ.get("NB_WORK_END") or cfg.get("work_end") or "18:00"
    return now, at(ws), at(we), tz


def _busy_today(tz):
    """Timed events across ALL authorized accounts that touch today (all-day
    events don't block hours, so they're skipped)."""
    today = datetime.now(tz).date()
    busy = []
    for k in auth.accounts_cfg():
        try:
            _email, items = list_events(k, days=1)
        except (SystemExit, Exception):
            continue
        for ev in items:
            sd = ev.get("start", {}).get("dateTime")
            ed = ev.get("end", {}).get("dateTime")
            if not sd or not ed:
                continue
            try:
                sdt = datetime.fromisoformat(sd).astimezone(tz)
                edt = datetime.fromisoformat(ed).astimezone(tz)
            except ValueError:
                continue
            if sdt.date() == today or edt.date() == today:
                busy.append((sdt, edt, ev.get("summary", "(busy)"), k))
    busy.sort(key=lambda b: b[0])
    return busy


def _free_slots(start_from, work_end, busy, block_min):
    """Greedy: walk the work window, emit block_min slots that clear every busy span."""
    slots, cur, step = [], start_from, timedelta(minutes=block_min)
    spans = [(s, e) for s, e, *_ in busy if e > start_from and s < work_end]
    while cur + step <= work_end:
        clash = next(((s, e) for s, e in spans if s < cur + step and e > cur), None)
        if clash:
            cur = clash[1]            # jump past the busy block
            continue
        slots.append((cur, cur + step))
        cur += step
    return slots


def cmd_planday(a):
    now, ws, we, tz = _work_window()
    block = a.block or int(os.environ.get("NB_BLOCK_MIN") or _planning_cfg().get("block_min") or 90)
    start_from = max(ws, now + timedelta(minutes=5))
    busy = _busy_today(tz)
    slots = _free_slots(start_from, we, busy, block)
    tasks = a.task or []

    print(f"# Plan for today — {ws.strftime('%H:%M')}–{we.strftime('%H:%M')}, {block}-min blocks")
    if busy:
        print(f"# {len(busy)} event(s) already booked today:")
        for s, e, title, k in busy:
            print(f"    {s.strftime('%H:%M')}–{e.strftime('%H:%M')}  [{k}] {title}")
    if not tasks:
        print("# free blocks:" if slots else "# no free blocks left today.")
        for s, e in slots[:6]:
            print(f"    {s.strftime('%H:%M')}–{e.strftime('%H:%M')}  (free)")
        return

    plan = list(zip(tasks, slots))
    print("# proposed blocks:")
    for t, (s, e) in plan:
        print(f"    {s.strftime('%H:%M')}–{e.strftime('%H:%M')}  {t}")
    for t in tasks[len(plan):]:
        print(f"    --:-- (no slot)  {t}")

    if a.commit:
        if unattended():
            sys.exit("REFUSED — writing calendar blocks is the owner's call; disabled for the operator.")
        service, _email = svc(a.account or "personal")
        tzname = local_tz()
        print(f"# committing {len(plan)} block(s) to [{a.account or 'personal'}]:")
        for t, (s, e) in plan:
            body = {"summary": f"🔵 {t}",
                    "start": {"dateTime": s.isoformat(), "timeZone": tzname},
                    "end": {"dateTime": e.isoformat(), "timeZone": tzname}}
            ev = service.events().insert(calendarId="primary", body=body,
                                         sendUpdates="none").execute()
            print(f"    ✓ {s.strftime('%H:%M')}  {t}")


def _free_gaps(start_from, work_end, busy):
    """Contiguous free spans in [start_from, work_end] not covered by busy, each
    >= 30 min (shorter gaps aren't worth surfacing)."""
    spans = sorted((s, e) for s, e, *_ in busy if e > start_from and s < work_end)
    gaps, cur = [], start_from
    for s, e in spans:
        s, e = max(s, start_from), min(e, work_end)
        if s > cur:
            gaps.append((cur, s))
        cur = max(cur, e)
    if cur < work_end:
        gaps.append((cur, work_end))
    return [(s, e) for s, e in gaps if (e - s) >= timedelta(minutes=30)]


def _hrs(h):
    return f"{h:.0f}" if abs(h - round(h)) < 0.1 else f"{h:.1f}"


def cmd_today(a):
    """Tight day summary for the brief. Line 1 is a speakable sentence; the rest
    is the booked events + free gaps for the Telegram/text push."""
    now, ws, we, tz = _work_window()
    start_from = max(ws, now)
    busy = _busy_today(tz)
    gaps = _free_gaps(start_from, we, busy)
    free_h = sum((e - s).total_seconds() for s, e in gaps) / 3600
    n = len(busy)
    line1 = f"{n} event{'' if n == 1 else 's'} today"
    if gaps:
        line1 += f" and {_hrs(free_h)} hours free"
    print(line1 + ".")
    for s, e, title, k in busy:
        print(f"  {s.strftime('%H:%M')}–{e.strftime('%H:%M')}  {title}")
    if gaps:
        print("Free: " + " · ".join(f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}" for s, e in gaps))


def main():
    ap = argparse.ArgumentParser(description="nathanbot calendar")
    ap.add_argument("--account", help="account key; omit only for 'agenda --all'")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--days", type=int, default=7)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--days", type=int, default=30)
    p = sub.add_parser("agenda"); p.add_argument("--days", type=int, default=1); p.add_argument("--all", action="store_true")
    p.add_argument("--past", action="store_true", help="look backward instead of forward (what already happened)")
    p = sub.add_parser("create")
    p.add_argument("--title", required=True); p.add_argument("--start", required=True)
    p.add_argument("--end", required=True); p.add_argument("--attendees"); p.add_argument("--yes")
    p.add_argument("--byday", help="weekly recurrence days, e.g. MO,WE,FR")
    p.add_argument("--rrule", help="raw RRULE body, e.g. FREQ=WEEKLY;BYDAY=TU,TH")
    p = sub.add_parser("find", help="ids of recurring MASTERS + single events (what update/delete take)")
    p.add_argument("query", nargs="?"); p.add_argument("--days", type=int, default=30)
    p = sub.add_parser("update", help="retitle / retime an event or whole series")
    p.add_argument("--id", required=True); p.add_argument("--title")
    p.add_argument("--time", help="new start time-of-day HH:MM; date and series anchor preserved")
    p.add_argument("--duration", type=int, help="new length in minutes")
    p.add_argument("--byday", help="new weekly recurrence, e.g. MO,TU,WE,TH")
    p.add_argument("--clear-recurrence", action="store_true",
                   help="demote a series back to a single event (undoes --byday)")
    p.add_argument("--yes", required=True, help="must restate the account key")
    p = sub.add_parser("delete", help="remove an event, or an entire recurring series")
    p.add_argument("--id", required=True)
    p.add_argument("--yes", required=True, help="must restate the account key")
    p = sub.add_parser("respond")
    p.add_argument("id"); p.add_argument("--status", required=True, choices=["accepted", "declined", "tentative"])
    p.add_argument("--yes", required=True, help="must restate the account key")
    p = sub.add_parser("planday")
    p.add_argument("--task", action="append", help="repeatable; a task title to time-block")
    p.add_argument("--block", type=int, help="block length in minutes (default 90)")
    p.add_argument("--commit", action="store_true", help="actually write the blocks to the calendar")
    sub.add_parser("today")  # day summary (events + free gaps) across all accounts
    a = ap.parse_args()

    # Exit 2, not 1: these are argparse's job done by hand -- the command worked,
    # the invocation was wrong. `sys.exit(str)` exits 1, which telemetry cannot
    # tell apart from a traceback, so every "nb cal list" typed without --account
    # was logged as a crash and audit section 15 counted it. A failure count that
    # rises when nothing is broken is one people stop reading.
    if a.cmd == "agenda":
        if not a.all and not a.account:
            _usage("agenda needs --account or --all")
    elif a.cmd in ("planday", "today"):
        pass  # account optional; reads all calendars, writes to personal by default
    elif not a.account:
        _usage("--account required")

    {"list": cmd_list, "search": cmd_search, "agenda": cmd_agenda,
     "find": cmd_find, "create": cmd_create, "update": cmd_update,
     "delete": cmd_delete, "respond": cmd_respond, "planday": cmd_planday,
     "today": cmd_today}[a.cmd](a)


if __name__ == "__main__":
    main()
