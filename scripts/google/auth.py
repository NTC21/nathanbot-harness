#!/usr/bin/env python3
"""Shared Google auth for nathanbot. Multi-account, credentials in ~/.secrets/google/.

  auth.py login <account>    consent + store refresh token (detects aliases)
  auth.py status             show every account/alias and whether it works
  auth.py verify <account>   prove the token still works
"""
import json, os, sys, pathlib

SECRETS = pathlib.Path.home() / ".secrets" / "google"
CLIENT = SECRETS / "client_secret.json"
ALIASES = SECRETS / "aliases.json"
ROOT = pathlib.Path(__file__).resolve().parents[2]
ACCOUNTS = ROOT / "config" / "accounts.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/calendar",
]


def _need(mod):
    try:
        __import__(mod)
    except ImportError:
        sys.exit(
            "Missing Google libraries. Install with:\n"
            "  uv pip install --system google-auth google-auth-oauthlib google-api-python-client\n"
            "or:  pip3 install google-auth google-auth-oauthlib google-api-python-client"
        )


def accounts_cfg():
    return json.load(open(ACCOUNTS))["accounts"]


def expected_email(key):
    a = accounts_cfg().get(key)
    if not a:
        sys.exit(f"unknown account '{key}'. Known: {', '.join(accounts_cfg())}")
    return a["email"]


def token_path(key):
    return SECRETS / f"{key}.json"


def load_aliases():
    return json.load(open(ALIASES)) if ALIASES.exists() else {}


def get_credentials(key):
    """Return credentials for an account key, following alias -> owner if needed."""
    _need("google.auth")
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    owner = load_aliases().get(key, key)
    tp = token_path(owner)
    if not tp.exists():
        sys.exit(f"'{key}' is not authorized yet. Run:  nb mail login {key}")
    creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tp.write_text(creds.to_json())
        os.chmod(tp, 0o600)
    return creds


def sending_identity(key):
    """(credentials, from_address) — from_address may be a send-as alias."""
    return get_credentials(key), expected_email(key)


def login(key):
    _need("google_auth_oauthlib")
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SECRETS.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS, 0o700)
    if not CLIENT.exists():
        sys.exit(
            f"Missing {CLIENT}\n"
            "Create an OAuth client (Desktop app) at console.cloud.google.com and save it there.\n"
            "Steps: docs/google-direct-auth.md"
        )

    want = expected_email(key)
    print(f"Authorizing: {want}")
    print("A browser will open. Make sure you consent as THAT account.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    # who did we actually get?
    profile = build("gmail", "v1", credentials=creds).users().getProfile(userId="me").execute()
    got = profile["emailAddress"].lower()

    if got != want.lower():
        # maybe the requested address is a send-as alias on the account we got
        aliases = [
            a["sendAsEmail"].lower()
            for a in build("gmail", "v1", credentials=creds)
            .users().settings().sendAs().list(userId="me").execute().get("sendAs", [])
        ]
        if want.lower() in aliases:
            owner = next((k for k, v in accounts_cfg().items() if v["email"].lower() == got), got)
            tp = token_path(owner)
            tp.write_text(creds.to_json())
            os.chmod(tp, 0o600)
            m = load_aliases()
            m[key] = owner
            ALIASES.write_text(json.dumps(m, indent=2))
            os.chmod(ALIASES, 0o600)
            print(f"\n✅ '{want}' is a send-as ALIAS on {got}")
            print(f"   token stored as '{owner}', alias recorded — `--account {key}` will work")
            return
        sys.exit(
            f"\n❌ WRONG ACCOUNT.\n"
            f"   requested: {want}\n   consented: {got}\n"
            f"   '{want}' is not a send-as alias there either.\n"
            f"   Sign out of Google or use a fresh browser profile, then retry."
        )

    tp = token_path(key)
    tp.write_text(creds.to_json())
    os.chmod(tp, 0o600)
    print(f"\n✅ authorized {want} -> {tp}")


def verify(key):
    from googleapiclient.discovery import build
    creds = get_credentials(key)
    p = build("gmail", "v1", credentials=creds).users().getProfile(userId="me").execute()
    print(f"  ✅ {key:<10} {p['emailAddress']}  ({p.get('messagesTotal','?')} messages)")


def status():
    cfg = accounts_cfg()
    aliases = load_aliases()
    print("Google accounts\n")
    if not CLIENT.exists():
        print(f"  ⚠️  no OAuth client yet — see docs/google-direct-auth.md\n")
    for key, a in sorted(cfg.items(), key=lambda kv: kv[1].get("rank", 99)):
        rank = a.get("rank", "?")
        if key in aliases:
            print(f"  {rank}. {key:<10} {a['email']:<34} alias on '{aliases[key]}'")
        elif token_path(key).exists():
            try:
                from googleapiclient.discovery import build
                creds = get_credentials(key)
                build("gmail", "v1", credentials=creds).users().getProfile(userId="me").execute()
                print(f"  {rank}. {key:<10} {a['email']:<34} ✅ authorized")
            except Exception as e:
                print(f"  {rank}. {key:<10} {a['email']:<34} ⚠️  token broken ({type(e).__name__})")
        else:
            print(f"  {rank}. {key:<10} {a['email']:<34} ❌ not authorized  (nb mail login {key})")
    print("\n  Lower rank number = higher precedence.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "login":
        if len(sys.argv) < 3:
            sys.exit("usage: nb mail login <account>")
        login(sys.argv[2])
    elif cmd == "verify":
        verify(sys.argv[2])
    elif cmd == "status":
        status()
    else:
        sys.exit(f"unknown: {cmd}")
