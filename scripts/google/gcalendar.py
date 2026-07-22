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
    # HARD FUSE: outward-facing calendar actions are Nathan's, never the operator's
    if attendees and os.environ.get("NB_OPERATOR"):
        sys.exit("REFUSED — inviting attendees sends invitations; disabled for the operator.\n"
                 "Nathan runs it himself from a terminal.")
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
    a = ap.parse_args()

    if a.cmd == "agenda":
        if not a.all and not a.account:
            sys.exit("agenda needs --account or --all")
    elif not a.account:
        sys.exit("--account required")

    {"list": cmd_list, "search": cmd_search, "agenda": cmd_agenda,
     "create": cmd_create, "respond": cmd_respond}[a.cmd](a)


if __name__ == "__main__":
    main()
