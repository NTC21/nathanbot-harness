#!/usr/bin/env python3
"""Google Docs writes for nathanbot. Drive API v3, multi-account via auth.py.

  drive.py push <account> <file.md> [--id ID] [--title T]   markdown -> Google Doc
  drive.py pull <account> <fileId> [dest]                   Google file -> local .xlsx/.docx/...
  drive.py show <account> <fileId>                          title, owner, url, modified
  drive.py list <account> [--query Q]                       docs this app created

Exists because of a real incident on 2026-08-01. The claude.ai Drive connector was
signed into a business Workspace account, and nothing in the connector surfaces
which account that is before a write — so an agent asked to "put my goals in a
Google Doc" created a document holding salary targets, a business exit decision and
a judgment about a named third party on the wrong Workspace entirely. It had to be
deleted by hand; the connector has no delete verb either.

The fix is not "be careful." It is `assert_identity()` below: every write resolves
the account key through config/accounts.json, asks Drive who the token actually
belongs to, and HARD-FAILS on a mismatch before touching anything. An agent cannot
write to the wrong Google account through this path even if it wants to.

(Kept deliberately account-agnostic: scripts/ ships wholesale in the public release
and its scan blocks on real account names. The lesson survives; the address doesn't.)

Uses drive.file scope (per-file, app-created only) rather than full drive on
purpose: this needs to create and update its own documents, not read the Drive.
The tradeoff is that it cannot update a Doc that the owner made by hand — push
without --id to get one this tool owns.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import auth  # noqa: E402

SCOPE_HINT = (
    "\n   This needs the Drive scope, which was added on 2026-08-01.\n"
    "   A token minted before that lacks it. Fix:  nb mail login {acct}\n"
)

DOC_MIME = "application/vnd.google-apps.document"

# Local suffix -> (its real mimetype, the Google-native type Drive converts it into).
# Conversion is the default for `upload` because an .xlsx sitting in Drive is a
# download, not a document: it cannot be edited on the phone, cannot be linked to,
# and every edit round-trips through the desktop. A native Sheet is the thing
# the owner actually wanted when he said "put it in my Drive". --raw opts out.
CONVERTIBLE = {
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.google-apps.spreadsheet",
    ),
    ".csv": ("text/csv", "application/vnd.google-apps.spreadsheet"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        DOC_MIME,
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.google-apps.presentation",
    ),
}


def _svc(account):
    from googleapiclient.discovery import build
    creds, addr = auth.sending_identity(account)
    return build("drive", "v3", credentials=creds), addr


def _call(fn, acct):
    """Run a Drive call, turning the two expected 403s into real instructions.

    Both of these are first-run states, not bugs, and both used to surface as a raw
    traceback — which reads like the tool is broken when the fix is one click or one
    command. They are distinct problems with distinct fixes, so they get distinct
    messages: a missing SCOPE is re-consent, a disabled API is a console toggle.
    """
    from googleapiclient.errors import HttpError
    try:
        return fn()
    except HttpError as e:
        msg = str(e)
        low = msg.lower()
        if e.resp.status in (401, 403) and ("accessnotconfigured" in low or "has not been used in project" in low):
            # The enable URL carries the project id, so lift it out of Google's own
            # message rather than hardcoding a project number into a repo that has a
            # public release path.
            import re
            m = re.search(r"https://console\.developers\.google\.com/apis/api/\S+?(?=[\s\"'])", msg)
            sys.exit(
                "\n❌ The Drive API is not enabled on this Google Cloud project.\n"
                "   Gmail, Calendar and Sheets are already on — Drive is a separate toggle\n"
                "   on the same OAuth client. Enable it here, wait ~1 min, then re-run:\n"
                f"\n   {m.group(0) if m else 'https://console.cloud.google.com/apis/library/drive.googleapis.com'}\n"
            )
        if e.resp.status in (401, 403) and ("insufficient" in low or "scope" in low):
            sys.exit(f"\n❌ Drive refused: {e.reason}" + SCOPE_HINT.format(acct=acct))
        raise


def assert_identity(svc, account, expected):
    """Prove the token belongs to the account we were asked to act as.

    auth.expected_email() reads the registry; this reads the live token. They can
    disagree — an alias mapping, a token minted against the wrong consent screen,
    a hand-edited accounts.json. The registry is an intention and the token is the
    fact, so the fact is what gets checked, and a disagreement is fatal rather
    than a warning. A warning would have been ignored on 2026-08-01.
    """
    who = _call(lambda: svc.about().get(fields="user(emailAddress)").execute(), account)
    got = (who.get("user", {}).get("emailAddress") or "").lower()
    if got != expected.lower():
        sys.exit(
            f"\n❌ WRONG ACCOUNT — refusing to write.\n"
            f"   asked to act as: {expected}  (account key '{account}')\n"
            f"   token belongs to: {got or '<unknown>'}\n"
            f"   Re-authorize with:  nb mail login {account}\n"
        )
    print(f"Acting as: {got}", file=sys.stderr)
    return got


def _media(path):
    from googleapiclient.http import MediaFileUpload
    # Drive converts text/markdown into a Doc with real headings and tables.
    # Uploading as text/plain instead produces one long unstyled paragraph block,
    # which is why the mimetype is pinned here rather than sniffed from the suffix.
    return MediaFileUpload(str(path), mimetype="text/markdown", resumable=False)


def cmd_push(a):
    path = pathlib.Path(a.file).expanduser().resolve()
    if not path.exists():
        sys.exit(f"no such file: {path}")

    svc, expected = _svc(a.account)
    assert_identity(svc, a.account, expected)

    fields = "id,name,webViewLink,modifiedTime"
    if a.id:
        f = _call(
            lambda: svc.files()
            .update(fileId=a.id, media_body=_media(path), fields=fields)
            .execute(),
            a.account,
        )
        verb = "updated"
    else:
        body = {"name": a.title or path.stem, "mimeType": DOC_MIME}
        f = _call(
            lambda: svc.files()
            .create(body=body, media_body=_media(path), fields=fields)
            .execute(),
            a.account,
        )
        verb = "created"

    print(f"  ✓ {verb}: {f['name']}")
    print(f"    id:  {f['id']}")
    print(f"    url: {f.get('webViewLink', '')}")
    if verb == "created":
        print(f"\n    Re-run with --id {f['id']} to update this doc instead of making another.")


def cmd_upload(a):
    """Local .xlsx/.csv/.docx/.pptx -> Drive, converted to the native Google type.

    Separate from push rather than folded into it: push pins text/markdown so a Doc
    comes out styled instead of as one flat paragraph, and that pin is exactly what
    an office file must not get. Same identity guard, same create-or---id update.
    """
    path = pathlib.Path(a.file).expanduser().resolve()
    if not path.exists():
        sys.exit(f"no such file: {path}")
    suffix = path.suffix.lower()
    if suffix not in CONVERTIBLE:
        sys.exit(
            f"don't know how to upload {suffix or '<no suffix>'} — "
            f"known: {', '.join(sorted(CONVERTIBLE))}"
        )
    src_mime, native_mime = CONVERTIBLE[suffix]

    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(path), mimetype=src_mime, resumable=False)

    svc, expected = _svc(a.account)
    assert_identity(svc, a.account, expected)

    fields = "id,name,webViewLink,modifiedTime,mimeType"
    if a.id:
        # No mimeType on update: the target file already IS a native Sheet/Doc, and
        # re-declaring it on a metadata patch is what turns an update into a type
        # change. The uploaded bytes still convert.
        f = _call(
            lambda: svc.files()
            .update(fileId=a.id, media_body=media, fields=fields)
            .execute(),
            a.account,
        )
        verb = "updated"
    else:
        body = {"name": a.title or path.stem}
        if not a.raw:
            body["mimeType"] = native_mime
        f = _call(
            lambda: svc.files()
            .create(body=body, media_body=media, fields=fields)
            .execute(),
            a.account,
        )
        verb = "created"

    kind = "native Google file" if not a.raw else "raw upload"
    print(f"  ✓ {verb} ({kind}): {f['name']}")
    print(f"    id:  {f['id']}")
    print(f"    url: {f.get('webViewLink', '')}")
    if verb == "created":
        print(f"\n    Re-run with --id {f['id']} to update this file instead of making another.")


def cmd_pull(a):
    """Native Google file -> local office file. The missing half of `upload`.

    Without this, the versioned snapshot in git can only ever drift: uploading is a
    replace, so a stale local copy cannot be safely re-pushed, and the only way back
    was File > Download by hand. `content-ops.xlsx` had silently fallen behind the
    live Sheet by two rows before anyone noticed.

    Writes through a temp file in the destination directory and renames on success.
    A half-written export must never land on top of the good snapshot — that turns a
    stale file, which is recoverable, into a corrupt one, which is not.
    """
    svc, expected = _svc(a.account)
    assert_identity(svc, a.account, expected)

    f = _call(
        lambda: svc.files().get(fileId=a.file_id, fields="id,name,mimeType").execute(),
        a.account,
    )
    native = f["mimeType"]
    if native.startswith("application/vnd.google-apps."):
        match = [(sfx, src) for sfx, (src, nat) in CONVERTIBLE.items() if nat == native]
        if not match:
            sys.exit(f"no export format known for {native}")
        suffix, export_mime = match[0]
        req = svc.files().export_media(fileId=a.file_id, mimeType=export_mime)
    else:
        # Already a blob (an --raw upload). Download it as-is; the name carries the type.
        suffix, export_mime = pathlib.Path(f["name"]).suffix, native
        req = svc.files().get_media(fileId=a.file_id)

    dest = pathlib.Path(a.dest).expanduser() if a.dest else pathlib.Path(f["name"] + suffix)
    if dest.is_dir():
        dest = dest / (f["name"] + suffix)
    dest = dest.resolve()
    if dest.suffix.lower() != suffix.lower():
        sys.exit(f"refusing to write {native} export to {dest.name} — expected a {suffix} destination")

    import io
    from googleapiclient.http import MediaIoBaseDownload

    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = _call(lambda: dl.next_chunk(), a.account)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    tmp.write_bytes(buf.getvalue())
    existed = dest.exists()
    tmp.replace(dest)

    print(f"  ✓ {'refreshed' if existed else 'pulled'}: {f['name']} -> {dest}")
    print(f"    {len(buf.getvalue()):,} bytes as {export_mime}")


def cmd_show(a):
    svc, expected = _svc(a.account)
    assert_identity(svc, a.account, expected)
    f = _call(
        lambda: svc.files()
        .get(fileId=a.file_id, fields="id,name,webViewLink,modifiedTime,owners(emailAddress)")
        .execute(),
        a.account,
    )
    owners = ", ".join(o.get("emailAddress", "?") for o in f.get("owners", []))
    print(f"{f['name']}")
    print(f"  owner:    {owners}")
    print(f"  modified: {f.get('modifiedTime', '')}")
    print(f"  url:      {f.get('webViewLink', '')}")


def cmd_list(a):
    svc, expected = _svc(a.account)
    assert_identity(svc, a.account, expected)
    q = a.query or f"mimeType = '{DOC_MIME}' and trashed = false"
    r = _call(
        lambda: svc.files()
        .list(q=q, pageSize=a.limit, fields="files(id,name,modifiedTime)", orderBy="modifiedTime desc")
        .execute(),
        a.account,
    )
    files = r.get("files", [])
    if not files:
        # drive.file scope only ever sees what this tool made. An empty list means
        # "nothing created here yet", never "the Drive is empty" — say so, because
        # the other reading is alarming and wrong.
        print("no docs created by nathanbot on this account yet (drive.file scope sees only its own)")
        return
    for f in files:
        print(f"{f['id']}  {f.get('modifiedTime', '')[:10]}  {f['name']}")


def main():
    p = argparse.ArgumentParser(prog="drive.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("push", help="markdown file -> Google Doc (create, or update with --id)")
    sp.add_argument("account")
    sp.add_argument("file")
    sp.add_argument("--id", help="update this doc instead of creating a new one")
    sp.add_argument("--title", help="doc title (default: the markdown filename)")
    sp.set_defaults(fn=cmd_push)

    su = sub.add_parser("upload", help="xlsx/csv/docx/pptx -> Drive, converted to a native Google file")
    su.add_argument("account")
    su.add_argument("file")
    su.add_argument("--id", help="update this file instead of creating a new one")
    su.add_argument("--title", help="file title (default: the local filename)")
    su.add_argument("--raw", action="store_true",
                    help="keep the original format instead of converting to a Google-native file")
    su.set_defaults(fn=cmd_upload)

    spl = sub.add_parser("pull", help="native Google file -> local xlsx/docx/pptx/csv")
    spl.add_argument("account")
    spl.add_argument("file_id")
    spl.add_argument("dest", nargs="?", help="output path or directory (default: the Drive name)")
    spl.set_defaults(fn=cmd_pull)

    ss = sub.add_parser("show", help="title, owner, url, modified time")
    ss.add_argument("account")
    ss.add_argument("file_id")
    ss.set_defaults(fn=cmd_show)

    sl = sub.add_parser("list", help="docs this tool created on that account")
    sl.add_argument("account")
    sl.add_argument("--query", help="raw Drive query (default: all non-trashed Docs)")
    sl.add_argument("--limit", type=int, default=25)
    sl.set_defaults(fn=cmd_list)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
