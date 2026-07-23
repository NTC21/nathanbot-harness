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


def _window(days):
    now = datetime.now(timezone.utc)
    return now.isoformat(), (now + timedelta(days=days)).isoformat()


def list_events(key, days=7, query=None):
    service, email = svc(key)
    tmin, tmax = _window(days)
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
    for k in keys:
        try:
            _email, items = list_events(k, a.days)
        except SystemExit:
            continue  # account not authorized — skip silently in --all
        except Exception as e:
            print(f"  ({k}: {e})", file=sys.stderr)
            continue
        for ev in items:
            st, title, loc = _fmt(ev)
            rows.append((st, k, title, loc))
    rows.sort(key=lambda r: r[0])
    print(f"# Agenda — next {a.days}d — {len(rows)} event(s) across {len(keys)} account(s)")
    for st, k, title, loc in rows:
        print(f"  {st}  [{k}] {title}" + (f"  @ {loc}" if loc else ""))


def cmd_create(a):
    attendees = [x.strip() for x in (a.attendees or "").split(",") if x.strip()]
    # HARD FUSE: outward-facing calendar actions are the owner's, never the operator's
    if attendees and os.environ.get("NB_OPERATOR"):
        sys.exit("REFUSED — inviting attendees sends invitations; disabled for the operator.\n"
                 "the owner runs it himself from a terminal.")
    if attendees and a.yes != a.account:
        sys.exit("Creating an event WITH attendees sends invitations (outward-facing).\n"
                 f"Re-run with:  --yes {a.account}")
    service, _email = svc(a.account)
    tz = local_tz()
    body = {"summary": a.title,
            "start": {"dateTime": a.start, "timeZone": tz},
            "end": {"dateTime": a.end, "timeZone": tz}}
    if attendees:
        body["attendees"] = [{"email": x} for x in attendees]
    ev = service.events().insert(
        calendarId="primary", body=body,
        sendUpdates="all" if attendees else "none").execute()
    print(f"created ({tz}): {ev.get('htmlLink')}")
    if attendees:
        print(f"  invited: {', '.join(attendees)}")


def cmd_respond(a):
    if os.environ.get("NB_OPERATOR"):
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
def _work_window():
    """(now, work_start, work_end, tzinfo) — all timezone-aware, today, local."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(local_tz())
    now = datetime.now(tz)

    def at(hhmm):
        h, m = (int(x) for x in hhmm.split(":"))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)
    return now, at(os.environ.get("NB_WORK_START", "09:00")), \
        at(os.environ.get("NB_WORK_END", "18:00")), tz


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
    block = a.block or int(os.environ.get("NB_BLOCK_MIN", "90"))
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
        if os.environ.get("NB_OPERATOR"):
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


def main():
    ap = argparse.ArgumentParser(description="nathanbot calendar")
    ap.add_argument("--account", help="account key; omit only for 'agenda --all'")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--days", type=int, default=7)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--days", type=int, default=30)
    p = sub.add_parser("agenda"); p.add_argument("--days", type=int, default=1); p.add_argument("--all", action="store_true")
    p = sub.add_parser("create")
    p.add_argument("--title", required=True); p.add_argument("--start", required=True)
    p.add_argument("--end", required=True); p.add_argument("--attendees"); p.add_argument("--yes")
    p = sub.add_parser("respond")
    p.add_argument("id"); p.add_argument("--status", required=True, choices=["accepted", "declined", "tentative"])
    p.add_argument("--yes", required=True, help="must restate the account key")
    p = sub.add_parser("planday")
    p.add_argument("--task", action="append", help="repeatable; a task title to time-block")
    p.add_argument("--block", type=int, help="block length in minutes (default 90)")
    p.add_argument("--commit", action="store_true", help="actually write the blocks to the calendar")
    a = ap.parse_args()

    if a.cmd == "agenda":
        if not a.all and not a.account:
            sys.exit("agenda needs --account or --all")
    elif a.cmd == "planday":
        pass  # account optional; reads all calendars, writes to personal by default
    elif not a.account:
        sys.exit("--account required")

    {"list": cmd_list, "search": cmd_search, "agenda": cmd_agenda,
     "create": cmd_create, "respond": cmd_respond, "planday": cmd_planday}[a.cmd](a)


if __name__ == "__main__":
    main()
