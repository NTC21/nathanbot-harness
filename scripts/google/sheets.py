#!/usr/bin/env python3
"""CRM writes for nathanbot. Google Sheets API v4, multi-account via auth.py.

  sheets.py append <crm> <csv>        append rows (data cols only; formulas rebuilt after)
  sheets.py touch  <crm> <org> <rung> stamp today's date on a ladder rung
  sheets.py repair <crm>              rebuild the Q:U auto-columns after a paste/import
  sheets.py due    <crm>              what's overdue / due today
  sheets.py show   <crm>              dump the pipeline

Exists because the claude.ai Drive connector has no write-to-existing-file verb —
it can search, read and create, but not edit. That forced a manual File > Import
once; this removes it. `nb crm` wraps these.

Writes only. Sending email is still the owner's act (see gmail.py cmd_send).
"""
import csv as csvmod
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import auth  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
CRM_CFG = ROOT / "config" / "crm.json"

SCOPE_HINT = (
    "\n   This needs the Sheets scope, which was added on 2026-07-27.\n"
    "   A token minted before that lacks it. Fix:  nb mail login {acct}\n"
)


def cfg(name):
    if not CRM_CFG.exists():
        sys.exit(f"missing {CRM_CFG}")
    crms = json.load(open(CRM_CFG))["crms"]
    if name not in crms:
        sys.exit(f"unknown crm '{name}'. Known: {', '.join(crms)}")
    c = crms[name]
    if not c.get("sheet_id"):
        sys.exit(
            f"\n❌ crm '{name}' has no sheet_id yet.\n"
            f"   {c.get('_sheet_id_todo', 'Set sheet_id in config/crm.json.')}\n"
        )
    return c


def svc(c):
    from googleapiclient.discovery import build
    creds, addr = auth.sending_identity(c["account"])
    print(f"Acting as: {addr}", file=sys.stderr)
    return build("sheets", "v4", credentials=creds)


def _call(fn, acct):
    """Run a Sheets call, turning the insufficient-scope 403 into a real instruction."""
    from googleapiclient.errors import HttpError
    try:
        return fn()
    except HttpError as e:
        if e.resp.status in (401, 403) and (
            "insufficient" in str(e).lower() or "scope" in str(e).lower()
        ):
            sys.exit(f"\n❌ Sheets refused: {e.reason}" + SCOPE_HINT.format(acct=acct))
        raise


def _formulas(row, cols):
    """The five auto-columns, rebuilt for a concrete row number.

    Kept identical to what the workbook already uses — the owner's Read Me tab tells
    him not to type in these, so they must survive an append untouched.
    """
    return [
        f'=IF($A{row}="","",IF($P{row}="Y","Responded",IF($O{row}<>"","Show Up",'
        f'IF($N{row}<>"","Phone Call",IF($M{row}<>"","LinkedIn DM",IF($L{row}<>"","Email 3",'
        f'IF($K{row}<>"","Email 2",IF($J{row}<>"","Email 1","Not Started"))))))))',
        f'=IF($A{row}="","",IF(COUNT($J{row}:$O{row})=0,"",MAX($J{row}:$O{row})))',
        f'=IF($A{row}="","",IF($P{row}="Y","— replied → advance Stage",'
        f'IF($Q{row}="Show Up","— ladder done (no reply)",IF($Q{row}="Phone Call","Show Up",'
        f'IF($Q{row}="LinkedIn DM","Phone Call",IF($Q{row}="Email 3","LinkedIn DM",'
        f'IF($Q{row}="Email 2","Email 3",IF($Q{row}="Email 1","Email 2","Email 1"))))))))',
        f'=IF($A{row}="","",IF($P{row}="Y","",IF($Q{row}="Not Started",TODAY(),'
        f'IF($Q{row}="Show Up","",$R{row}+3))))',
        f'=IF($A{row}="","",IF($P{row}="Y","✅ REPLIED",IF(OR($I{row}="Won",$I{row}="Pilot"),'
        f'"🏆 "&UPPER($I{row}),IF($I{row}="Lost","⚫ LOST",IF($Q{row}="Show Up","🔵 EXHAUSTED - decide",'
        f'IF($T{row}="","",IF($T{row}<TODAY(),"🔴 OVERDUE",IF($T{row}=TODAY(),"🟡 DUE TODAY","🟢 On track"))))))))',
    ]


def _read_col(s, c, col):
    r = _call(lambda: s.spreadsheets().values().get(
        spreadsheetId=c["sheet_id"], range=f"{c['tab']}!{col}:{col}"
    ).execute(), c["account"])
    return [v[0] if v else "" for v in r.get("values", [])]


def cmd_append(name, path):
    c = cfg(name)
    s = svc(c)
    rows = [r for r in csvmod.reader(open(path, encoding="utf-8")) if any(x.strip() for x in r)]
    if rows and rows[0][0].strip().lower().startswith("org"):
        rows = rows[1:]  # tolerate a header
    if not rows:
        sys.exit("no data rows in " + path)

    # Append A:P + V only. Q-U are rebuilt afterwards, once the real row numbers
    # are known — you cannot write a self-referencing formula before you know
    # which row it lands on.
    body = [r[:16] + [""] * 5 + [r[21] if len(r) > 21 else ""] for r in rows]
    res = _call(lambda: s.spreadsheets().values().append(
        spreadsheetId=c["sheet_id"], range=f"{c['tab']}!A:V",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": body},
    ).execute(), c["account"])

    rng = res["updates"]["updatedRange"]            # e.g. Pipeline!A8:V53
    first = int("".join(ch for ch in rng.split("!")[1].split(":")[0] if ch.isdigit()))
    last = first + len(body) - 1

    _call(lambda: s.spreadsheets().values().update(
        spreadsheetId=c["sheet_id"], range=f"{c['tab']}!Q{first}:U{last}",
        valueInputOption="USER_ENTERED",
        body={"values": [_formulas(first + i, c) for i in range(len(body))]},
    ).execute(), c["account"])

    print(f"\n  ✅ appended {len(body)} rows at {c['tab']}!{first}-{last}")
    print(f"     formulas rebuilt in Q{first}:U{last}")
    print(f"     https://docs.google.com/spreadsheets/d/{c['sheet_id']}/edit")


def cmd_touch(name, org, rung):
    c = cfg(name)
    if rung not in c["rungs"]:
        sys.exit(f"unknown rung '{rung}'. Known: {', '.join(c['rungs'])}")
    s = svc(c)
    col = c["rungs"][rung]
    orgs = _read_col(s, c, c["columns"]["org"])

    hits = [i + 1 for i, v in enumerate(orgs)
            if v.strip().lower() == org.strip().lower()]
    if not hits:
        hits = [i + 1 for i, v in enumerate(orgs)
                if org.strip().lower() in v.strip().lower()]
    if not hits:
        sys.exit(f"no row matching '{org}'")
    if len(hits) > 1:
        sys.exit(f"'{org}' matches {len(hits)} rows ({hits}) — be more specific")

    row = hits[0]
    today = datetime.date.today().strftime("%-m/%-d/%Y")
    _call(lambda: s.spreadsheets().values().update(
        spreadsheetId=c["sheet_id"], range=f"{c['tab']}!{col}{row}",
        valueInputOption="USER_ENTERED", body={"values": [[today]]},
    ).execute(), c["account"])
    print(f"  ✅ {orgs[row-1]} — {rung} logged {today} ({col}{row})")


def _pipeline(s, c):
    r = _call(lambda: s.spreadsheets().values().get(
        spreadsheetId=c["sheet_id"], range=f"{c['tab']}!A:V"
    ).execute(), c["account"])
    vals = r.get("values", [])
    return [v + [""] * (22 - len(v)) for v in vals[1:] if v and v[0].strip()]


def cmd_rm(name, *orgs):
    """Delete rows by org name. Prints exactly what it will remove first.

    Deletes bottom-up: removing a row shifts every row beneath it, so descending
    order keeps the remaining indices valid.
    """
    c = cfg(name)
    s = svc(c)
    all_orgs = _read_col(s, c, c["columns"]["org"])

    targets, missing = [], []
    for want in orgs:
        hits = [i + 1 for i, v in enumerate(all_orgs)
                if v.strip().lower() == want.strip().lower()]
        if not hits:
            hits = [i + 1 for i, v in enumerate(all_orgs)
                    if want.strip().lower() in v.strip().lower()]
        if not hits:
            missing.append(want)
        elif len(hits) > 1:
            sys.exit(f"'{want}' matches {len(hits)} rows {hits} — be more specific")
        else:
            targets.append((hits[0], all_orgs[hits[0] - 1]))

    if missing:
        sys.exit(f"\n❌ no row matching: {missing}\n   Nothing deleted.")

    print(f"\n  removing {len(targets)} rows:")
    for row, org in sorted(targets):
        print(f"    row {row:>3}  {org}")

    tab_id = next(t["properties"]["sheetId"] for t in
                  _call(lambda: s.spreadsheets().get(spreadsheetId=c["sheet_id"]).execute(),
                        c["account"])["sheets"]
                  if t["properties"]["title"] == c["tab"])

    reqs = [{"deleteDimension": {"range": {
        "sheetId": tab_id, "dimension": "ROWS",
        "startIndex": row - 1, "endIndex": row}}}
        for row, _ in sorted(targets, reverse=True)]
    _call(lambda: s.spreadsheets().batchUpdate(
        spreadsheetId=c["sheet_id"], body={"requests": reqs}).execute(), c["account"])
    print(f"\n  ✅ removed {len(targets)} rows — run `nb crm repair {name}` to reindex formulas")


def cmd_repair(name):
    """Rewrite Q:U for every populated row.

    A CSV import or a hand paste drops trailing cells, so the auto-columns go
    blank and the row silently falls out of the due list — it looks handled when
    it isn't. Idempotent: the formulas are a pure function of the row number.
    """
    c = cfg(name)
    s = svc(c)
    orgs = _read_col(s, c, c["columns"]["org"])
    first = c.get("first_data_row", 2)
    last = max((i + 1 for i, v in enumerate(orgs) if v.strip()), default=0)
    if last < first:
        sys.exit("no data rows found")
    n = last - first + 1
    _call(lambda: s.spreadsheets().values().update(
        spreadsheetId=c["sheet_id"], range=f"{c['tab']}!Q{first}:U{last}",
        valueInputOption="USER_ENTERED",
        body={"values": [_formulas(first + i, c) for i in range(n)]},
    ).execute(), c["account"])
    print(f"  ✅ rebuilt Q{first}:U{last} ({n} rows)")


def cmd_due(name):
    c = cfg(name)
    rows = _pipeline(svc(c), c)
    hot = [r for r in rows if "OVERDUE" in r[20] or "DUE TODAY" in r[20]]
    if not hot:
        print("\n  nothing due. 🟢")
        return
    print(f"\n  {len(hot)} due:\n")
    for r in sorted(hot, key=lambda x: 0 if "OVERDUE" in x[20] else 1):
        print(f"  {r[20]:<14} {r[0][:34]:<36} {r[18][:22]:<24} {r[7]}")
    print()


def cmd_show(name):
    c = cfg(name)
    rows = _pipeline(svc(c), c)
    print(f"\n  {len(rows)} targets\n")
    for r in rows:
        print(f"  {r[20]:<14} {r[0][:34]:<36} {r[8]:<10} {r[16][:14]:<16} {r[7]}")
    print()


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    try:
        if cmd == "append":
            cmd_append(a[1], a[2])
        elif cmd == "touch":
            cmd_touch(a[1], a[2], a[3])
        elif cmd == "rm":
            cmd_rm(a[1], *a[2:])
        elif cmd == "repair":
            cmd_repair(a[1])
        elif cmd == "due":
            cmd_due(a[1])
        elif cmd == "show":
            cmd_show(a[1])
        else:
            sys.exit(__doc__)
    except IndexError:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
