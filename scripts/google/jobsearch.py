#!/usr/bin/env python3
"""Job-search tracker reads for nathanbot. Google Sheets API v4.

  jobsearch.py due     what needs action today
  jobsearch.py show    the live pipeline (Tier 1/2, not dead)

Parallel to sheets.py (the sales CRM) but a different schema: the CRM runs an
escalation ladder with rung columns, this runs two flat tabs with date columns.
Read-only on purpose - the owner edits the sheet, this only nags.

The rule that earns its keep is ACCEPTED-BUT-NEVER-MESSAGED. Tracking who you sent
a LinkedIn invite to is easy; noticing they accepted three days ago and you never
followed up is the part that actually loses referrals.
"""
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import auth  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "jobsearch.json"
B, D, G, Y, R_, X = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"


def cfg():
    if not CFG.exists():
        sys.exit(f"missing {CFG}")
    return json.load(open(CFG))


def svc(c):
    from googleapiclient.discovery import build
    creds, addr = auth.sending_identity(c["account"])
    return build("sheets", "v4", credentials=creds), addr


def grid(s, c, tabname):
    t = c["tabs"][tabname]
    vals = s.spreadsheets().values().get(
        spreadsheetId=c["sheet_id"], range=f"'{t['tab']}'").execute().get("values", [])
    cols = t["columns"]
    idx = {k: ord(v) - 65 for k, v in cols.items()}
    out = []
    for r in vals[t["first_data_row"] - 1:]:
        if not any(str(x).strip() for x in r):
            continue
        out.append({k: (r[i].strip() if i < len(r) and r[i] else "") for k, i in idx.items()})
    return out, t


def _date(s):
    try:
        return datetime.date.fromisoformat(s.strip())
    except Exception:
        return None


def cmd_due():
    c = cfg()
    s, addr = svc(c)
    today = datetime.date.today()
    apps, at = grid(s, c, "applications")
    out, ot = grid(s, c, "outreach")
    dead = set(at["dead_statuses"])

    # 1. accepted but never messaged - the window you actually lose
    hot = [r for r in out if r["accepted"].upper() == "Y" and r["message_sent"].upper() != "Y"]
    # 2. overdue application follow-ups
    late = [r for r in apps if (d := _date(r["followup"])) and d <= today and r["status"] not in dead]
    # 3. invites sent with no response, past the stale window
    stale_days = ot.get("stale_after_days", 10)
    stale = [r for r in out
             if (d := _date(r["date_sent"])) and not r["accepted"]
             and (today - d).days >= stale_days]
    # 4. nudges due
    nudge = [r for r in out if (d := _date(r["next_nudge"])) and d <= today
             and r["referral"] not in ("Got it", "Declined")]

    n = len(hot) + len(late) + len(stale) + len(nudge)
    if not n:
        print("\n  job search: nothing due. 🟢\n")
        return

    print(f"\n  {B}JOB SEARCH — {n} item(s) due{X}   {D}({addr}){X}\n")
    if hot:
        print(f"  {R_}{B}ACCEPTED, NOT MESSAGED{X}  — send the real message now")
        for r in hot:
            print(f"    • {r['name']:<24} {r['company']:<14} {D}{r['title'][:30]}{X}")
        print()
    if late:
        print(f"  {Y}{B}FOLLOW-UP OVERDUE{X}")
        for r in sorted(late, key=lambda r: r["followup"]):
            print(f"    • {r['followup']}  {r['company']:<16} {r['position'][:34]:<36} "
                  f"{D}T{r['tier'] or '-'} {r['status']}{X}")
        print()
    if nudge:
        print(f"  {Y}{B}OUTREACH NUDGE DUE{X}")
        for r in sorted(nudge, key=lambda r: r["next_nudge"]):
            print(f"    • {r['next_nudge']}  {r['name']:<24} {r['company']}")
        print()
    if stale:
        print(f"  {D}NO RESPONSE {stale_days}d+ — try another contact{X}")
        for r in stale:
            print(f"    • {r['date_sent']}  {r['name']:<24} {r['company']}")
        print()


def cmd_show():
    c = cfg()
    s, _ = svc(c)
    apps, at = grid(s, c, "applications")
    dead = set(at["dead_statuses"])
    live = [r for r in apps if r["status"] not in dead and r["tier"] in ("1", "2")]
    print(f"\n  {len(live)} live Tier 1/2\n")
    for r in sorted(live, key=lambda r: (r["tier"], r["company"])):
        print(f"  T{r['tier']} {r['status']:<14} {r['company']:<16} {r['position'][:32]:<34} "
              f"{r['comp'] or '-':<12} {D}{r['contact'][:24]}{X}")
    print()


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
    elif a[0] == "due":
        cmd_due()
    elif a[0] == "show":
        cmd_show()
    else:
        sys.exit(f"unknown cmd '{a[0]}' (due|show)")
