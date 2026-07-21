#!/usr/bin/env python3
"""Gmail for nathanbot. --account is ALWAYS required. send takes a draft id only.

  gmail.py --account <k> search "<query>" [--limit N]
  gmail.py --account <k> read <message-id>
  gmail.py --account <k> draft --to <addr> --subject "<s>" --body "<b>"
  gmail.py --account <k> send <draft-id> --yes <account-key>
  gmail.py --account <k> labels
"""
import argparse, base64, sys, pathlib
from email.mime.text import MIMEText

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import auth  # noqa: E402


def permission(path):
    """Read a permission level from config/permissions.json. Enforced, not advisory."""
    import json, pathlib
    cfg = pathlib.Path(__file__).resolve().parents[2] / "config" / "permissions.json"
    d = json.load(open(cfg))
    for part in path.split("."):
        d = d.get(part, {})
    return d.get("level", "ask") if isinstance(d, dict) else "ask"


def require(path, what):
    """Refuse unless the permission is 'always'."""
    lvl = permission(path)
    if lvl == "always":
        return
    if lvl == "never":
        sys.exit(f"\n❌ REFUSED — '{path}' is set to NEVER in config/permissions.json.\n"
                 f"   {what}\n   Change that file if this should be allowed.")
    sys.exit(f"\n⛔ PERMISSION REQUIRED — '{path}' is set to ASK.\n"
             f"   {what}\n"
             f"   the owner must approve this explicitly. To allow it permanently, set\n"
             f"   \"{path}\" -> level: \"always\" in config/permissions.json")


def headers(payload):
    """Gmail returns header names with inconsistent casing (To vs to) depending on
    format/endpoint. Always look them up case-insensitively."""
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def svc(key):
    from googleapiclient.discovery import build
    creds, addr = auth.sending_identity(key)
    print(f"Acting as: {addr}", file=sys.stderr)
    return build("gmail", "v1", credentials=creds), addr


def cmd_search(a):
    s, _ = svc(a.account)
    res = s.users().messages().list(userId="me", q=a.query, maxResults=a.limit).execute()
    msgs = res.get("messages", [])
    if not msgs:
        print("no results")
        return
    for m in msgs:
        d = s.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]).execute()
        h = headers(d["payload"])
        print(f"{m['id']}  {h.get('date','')[:16]:<18} {h.get('from','')[:32]:<34} {h.get('subject','')[:50]}")


def _body(payload):
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for p in payload.get("parts", []):
        if p.get("mimeType") == "text/plain":
            return _body(p)
    for p in payload.get("parts", []):
        t = _body(p)
        if t:
            return t
    return ""


def cmd_read(a):
    if not a.approved:
        require("email.read_bodies",
                f"Reading the full body of message {a.id}. Subjects/metadata are always allowed; bodies are not.")
    s, _ = svc(a.account)
    d = s.users().messages().get(userId="me", id=a.id, format="full").execute()
    h = headers(d["payload"])
    for k in ("from", "to", "date", "subject"):
        print(f"{k.title()}: {h.get(k,'')}")
    print("-" * 60)
    print(_body(d["payload"])[:4000])


def cmd_draft(a):
    s, addr = svc(a.account)
    m = MIMEText(a.body)
    m["to"], m["from"], m["subject"] = a.to, addr, a.subject
    raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
    d = s.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    print(f"\n  draft id: {d['id']}")
    print(f"  from:     {addr}\n  to:       {a.to}\n  subject:  {a.subject}")
    print(f"\n  Review it, then:")
    print(f"    nb mail --account {a.account} send {d['id']} --yes {a.account}")


def cmd_send(a):
    # the account must be restated — a bare --yes is too easy to add reflexively
    if a.yes != a.account:
        sys.exit(
            f"\n❌ REFUSED. --yes must restate the account.\n"
            f"   sending as: {a.account}\n   you typed:  --yes {a.yes}\n"
            f"   If {a.account} is correct:  --yes {a.account}"
        )
    s, addr = svc(a.account)
    d = s.users().drafts().get(userId="me", id=a.id, format="metadata").execute()
    h = headers(d["message"]["payload"])
    to, subj = h.get("to", ""), h.get("subject", "")
    if not to:
        sys.exit(f"\n❌ REFUSED. Could not read the recipient for draft {a.id}.\n"
                 f"   Refusing to send something it cannot show you.")
    print(f"\n  SENDING\n  from: {addr}\n  to:   {to}\n  subj: {subj}")
    s.users().drafts().send(userId="me", body={"id": a.id}).execute()
    print("  ✅ sent")


def cmd_labels(a):
    # listing labels is metadata, always fine
    s, _ = svc(a.account)
    for l in s.users().labels().list(userId="me").execute().get("labels", []):
        print(f"  {l['id']:<28} {l['name']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Gmail — account always explicit")
    p.add_argument("--account", required=True, help="account key from config/accounts.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("search"); s1.add_argument("query"); s1.add_argument("--limit", type=int, default=10)
    s2 = sub.add_parser("read"); s2.add_argument("id")
    s2.add_argument("--approved", action="store_true",
                    help="the owner explicitly approved reading this body in the conversation")
    s3 = sub.add_parser("draft")
    s3.add_argument("--to", required=True); s3.add_argument("--subject", required=True); s3.add_argument("--body", required=True)
    s4 = sub.add_parser("send"); s4.add_argument("id"); s4.add_argument("--yes", required=True, help="must restate the account key")
    sub.add_parser("labels")

    a = p.parse_args()
    {"search": cmd_search, "read": cmd_read, "draft": cmd_draft,
     "send": cmd_send, "labels": cmd_labels}[a.cmd](a)
