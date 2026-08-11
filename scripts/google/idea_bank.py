#!/usr/bin/env python3
"""Drain the idea-bank staging file into the Idea Bank tab of Content Ops.

  idea_bank.py drain [--dry-run]   append every staged idea, then clear the file

Exists because the staging file was a manual copy-paste step, and manual steps rot —
the 2026-08-03 ideas were still sitting in it a day later. Appending rows through the
Sheets API is non-destructive, unlike `nb drive upload`, which overwrites the whole
workbook and eats live edits. Nothing outside the appended rows is touched.

Staging format (see scripts/ideas.sh):

    ## 2026-08-04

    1. [F3] HOOK: the hook line.
       - beat
       - beat
       WHY NOW: why this is worth filming today.

maps to  A=captured  B=hook + beats  C=format  D=pillar  E=source (the WHY NOW line).
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import auth  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "sheets.json"
STAGING = ROOT / "workspace-creative" / "idea-bank-staging.md"

# Free text in the sheet, but "AI system" is the only value the workbook uses today.
# Every format in the playbook is a lane-Main video about the system, so this holds
# until a second pillar actually exists.
DEFAULT_PILLAR = "AI system"

SCOPE_HINT = (
    "\n   This needs the Sheets scope, which was added on 2026-07-27.\n"
    "   A token minted before that lacks it. Fix:  nb mail login {acct}\n"
)

DATE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$")
IDEA = re.compile(r"^(\d+)\.\s+(?:\[(F\d)\]\s*)?(.*)$")


def cfg(sheet="content-ops", tab="idea_bank"):
    if not CFG.exists():
        sys.exit(f"missing {CFG}")
    d = json.load(open(CFG))["sheets"]
    if sheet not in d:
        sys.exit(f"unknown sheet '{sheet}'. Known: {', '.join(d)}")
    c = d[sheet]
    if tab not in c["tabs"]:
        sys.exit(f"unknown tab '{tab}'. Known: {', '.join(c['tabs'])}")
    return c, c["tabs"][tab]


def parse(text):
    """-> [(captured, hook_block, format, source)] in file order."""
    out, date, cur = [], None, None

    def flush():
        if cur is None:
            return
        body = "\n".join(cur["lines"]).strip()
        out.append((cur["date"], body, cur["fmt"], cur["why"]))

    for raw in text.splitlines():
        line = raw.rstrip()
        m = DATE.match(line)
        if m:
            flush()
            cur, date = None, m.group(1)
            continue
        m = IDEA.match(line.strip()) if line.strip()[:1].isdigit() else None
        if m and date:
            flush()
            cur = {"date": date, "fmt": m.group(2) or "", "lines": [m.group(3)], "why": ""}
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.upper().startswith("WHY NOW:"):
            cur["why"] = s[len("WHY NOW:"):].strip()
        elif s:
            cur["lines"].append(s)
    flush()
    return out


def strip_staged(text):
    """Keep the header block, drop every dated section. Returns the new file body."""
    lines, out = text.splitlines(), []
    for line in lines:
        if DATE.match(line.rstrip()):
            break
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def main():
    args = sys.argv[1:]
    if not args or args[0] != "drain":
        sys.exit(__doc__)
    dry = "--dry-run" in args

    if not STAGING.exists():
        sys.exit("no staging file — nothing to drain")
    text = STAGING.read_text(encoding="utf-8")
    ideas = parse(text)
    if not ideas:
        print("staging is empty — nothing to drain")
        return

    rows = [[d, hook, fmt, DEFAULT_PILLAR, why] for d, hook, fmt, why in ideas]

    print(f"\n  {len(rows)} idea(s) to append to Idea Bank:\n")
    for r in rows:
        print(f"  {r[0]}  {r[2] or '--':<3} {r[1].splitlines()[0][:66]}")
    if dry:
        print("\n  --dry-run, nothing written\n")
        return

    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    c, t = cfg()
    creds, addr = auth.sending_identity(c["account"])
    print(f"\nActing as: {addr}")
    s = build("sheets", "v4", credentials=creds)
    try:
        res = s.spreadsheets().values().append(
            spreadsheetId=c["sheet_id"], range=f"{t['tab']}!{t['range']}",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
    except HttpError as e:
        if e.resp.status in (401, 403) and (
            "insufficient" in str(e).lower() or "scope" in str(e).lower()
        ):
            sys.exit(f"\n❌ Sheets refused: {e.reason}" + SCOPE_HINT.format(acct=c["account"]))
        raise

    print(f"  ✅ appended {res['updates']['updatedRange']}")
    STAGING.write_text(strip_staged(text), encoding="utf-8")
    print(f"  ✅ cleared {STAGING.relative_to(ROOT)}")
    print(f"     https://docs.google.com/spreadsheets/d/{c['sheet_id']}/edit\n")


if __name__ == "__main__":
    main()
