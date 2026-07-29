#!/usr/bin/env python3
"""nathanbot — headless local server. No build step, no deps beyond stdlib.
A JSON API on :7777 over the real task/memory files. There is no dashboard;
the clients are the Telegram bridge, the voice daemon, and bin/nb.
"""
import json, os, re, socket, subprocess, pathlib, http.server, threading, time, urllib.parse

R = pathlib.Path(__file__).resolve().parents[1]
OPEN, DONE, ARCH = R/"tasks"/"open", R/"tasks"/"done", R/"tasks"/"archive"
PORT = int(os.environ.get("NB_UI_PORT", "7777"))
NB = str(R/"bin"/"nb")

import sys
sys.path.insert(0, str(R/"scripts"/"voice"))
from prompt import (build_operator_prompt, operator_allowed_tools,
                    operator_denied_tools, operator_add_dirs)  # shared with voice


def _which_claude():
    """LaunchAgents get a minimal PATH — resolve the binary explicitly."""
    import shutil
    for c in (shutil.which("claude"),
              os.path.expanduser("~/.local/bin/claude"),
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude",
              os.path.expanduser("~/.claude/local/claude")):
        if c and os.path.exists(c):
            return c
    return "claude"


CLAUDE_BIN = _which_claude()

# Pass a hardened PATH to every nb subprocess so it works when the server is
# launched outside the LaunchAgent. This was originally a workaround for nb's
# `command -v claude` gate, which failed under a bare PATH; that gate now asks
# claudew (NB_CHECK=1) and resolves independently, so this is defence in depth
# for the rest of nb's shell-outs rather than the thing holding it together.
_HARDENED_PATH = os.pathsep.join([
    os.path.dirname(CLAUDE_BIN), "/opt/homebrew/bin", "/usr/local/bin",
    "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    os.path.join(os.environ.get("HOME", os.path.expanduser("~")), ".local", "bin"),
    os.environ.get("PATH", ""),   # keep whatever launchd/login already provided
])
NB_ENV = {**os.environ, "PATH": _HARDENED_PATH}


def chat_model():
    """Model for operator chat. NB_CHAT_MODEL env beats config/server.json.
    Alias names (opus/sonnet/haiku) are still preferred over pinned model IDs:
    an alias tracks the current model, a pinned ID silently goes stale."""
    m = os.environ.get("NB_CHAT_MODEL", "").strip()
    if m:
        return m
    try:
        return (json.loads((R/"config"/"server.json").read_text())
                .get("chat_model") or "sonnet").strip()
    except Exception:
        return "sonnet"


def chat_effort():
    """Reasoning effort for operator chat, or "" to leave the CLI default alone.

    Validated against the levels the CLI accepts rather than passed through
    blindly: a bad --effort value makes claude exit non-zero, and every reply
    becomes "couldn't reach the brain" — the same silent-channel failure the
    Telegram API/SERVER name collision caused.
    """
    LEVELS = {"low", "medium", "high", "xhigh", "max"}
    e = os.environ.get("NB_CHAT_EFFORT", "").strip()
    if not e:
        try:
            e = (json.loads((R/"config"/"server.json").read_text())
                 .get("chat_effort") or "").strip()
        except Exception:
            e = ""
    return e if e in LEVELS else ""


def nb(*args, timeout=600):
    """Run an nb subcommand with the hardened env; return cleaned stdout+stderr.

    NB_OPERATOR is set here, not only on /api/chat. Without it, /api/say and
    /api/run bypassed every fuse the comment on the chat route claims protects
    them — route_say allows /tidy and passes the remainder through as argv, so a
    local POST of {"text": "/tidy --apply"} reached `nb tidy --apply` with the
    guard at bin/nb inert, and that runs rm -rf over dormant node_modules.
    """
    r = subprocess.run([NB, *args], capture_output=True, text=True,
                       timeout=timeout, env={**NB_ENV, "NB_OPERATOR": "1"})
    return re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or "")), r.returncode


def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s or "")


# ── operator tool scope ──────────────────────────────────────────────────────
# Moved to scripts/voice/prompt.py so the chat and voice channels share ONE
# definition. They had already drifted: this file enumerated the nb verbs and
# derived the credential denylist from nb_guard, while jarvis.py kept a
# Bash(<nb>:*) wildcard and denied only ~/.secrets.


# ── operator-drafts-then-the owner-approves email send ──────────────────────────
# The operator can NEVER send (gmail.py is NB_OPERATOR-fused, and the operator
# has no POST-capable tool). It only STAGES: it emits a [[SEND_DRAFT]] marker,
# the server reads the draft's REAL recipient/subject server-side, and the UI
# shows an approval card. Only the owner's browser click (POST, which the operator
# cannot make) fires the actual send. Tokens are single-use and expire fast.
_SEND_TOKENS = {}          # token -> (draft_id, account, expiry_epoch)
_SEND_ACCOUNT = "personal"  # only authorized sending identity
_SEND_MARKER = re.compile(r"\[\[\s*SEND_DRAFT(?:\s+to=([^\]\s]+))?\s*\]\]", re.I)


def _gmail(account, *args, timeout=30, drop_operator=False):
    env = dict(NB_ENV)
    if drop_operator:
        # BOTH. This is the owner's own act, redeemed via a single-use token he
        # approved — not the operator's. gmail.py and gcalendar.py refuse on
        # either flag, so dropping only one would leave the approve button
        # broken if the server were ever started from a claudew session.
        env.pop("NB_OPERATOR", None)
        env.pop("NB_UNATTENDED", None)
    r = subprocess.run(["python3", str(R/"scripts"/"google"/"gmail.py"),
                        "--account", account, *args],
                       capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, _strip_ansi(r.stdout).strip(), _strip_ansi(r.stderr).strip()


def _prepare_send(to_hint=None):
    """Read the newest draft (optionally matching a recipient) and mint a one-use
    approval token. Returns the dict the UI card renders — TRUE values, read here,
    not whatever the model asserted."""
    import secrets
    rc, out, err = _gmail(_SEND_ACCOUNT, "drafts", "--limit", "10")
    if rc != 0:
        return {"ok": False, "error": err or "could not list drafts"}
    try:
        drafts = json.loads(out or "[]")
    except json.JSONDecodeError:
        return {"ok": False, "error": "could not parse drafts"}
    pick = None
    for d in drafts:                                   # drafts() returns newest first
        if to_hint:
            if to_hint.lower() in (d.get("to") or "").lower():
                pick = d
                break
        else:
            pick = d
            break
    if not pick:
        return {"ok": False, "error": f"no draft found to {to_hint}" if to_hint else "no drafts"}
    if not (pick.get("to") or "").strip():
        return {"ok": False, "error": "that draft has no recipient set — can't send it"}
    token = secrets.token_urlsafe(24)
    _SEND_TOKENS[token] = (pick["draft_id"], pick["account"], time.time() + 300)
    return {"ok": True, "token": token, "draft_id": pick["draft_id"],
            "to": pick["to"], "subject": pick.get("subject", ""),
            "account": pick["account"], "from": pick.get("from", "")}


# ── operator-stages-then-the owner-approves calendar block ──────────────────────
# Exactly the email pattern: gcalendar.py create is NB_OPERATOR-fused (even a
# self-block), so the operator can only STAGE a block via a [[CAL_BLOCK]] marker.
# The server validates the times, mints a one-use token, and only the owner's tap
# (a POST the operator can't make) writes the event — WITHOUT NB_OPERATOR.
_CAL_TOKENS = {}           # token -> (title, start_iso, end_iso, account, expiry_epoch)
_CAL_ACCOUNT = "personal"  # blocks land on the personal calendar
_CAL_MARKER = re.compile(
    r"\[\[\s*CAL_BLOCK\s+title=(?P<title>[^|\]]+?)\s*\|\s*"
    r"start=(?P<start>[^|\]\s]+)\s*\|\s*end=(?P<end>[^|\]\s]+)\s*\]\]", re.I)


def _gcal(*args, timeout=30, drop_operator=False):
    env = dict(NB_ENV)
    if drop_operator:
        # BOTH. This is the owner's own act, redeemed via a single-use token he
        # approved — not the operator's. gmail.py and gcalendar.py refuse on
        # either flag, so dropping only one would leave the approve button
        # broken if the server were ever started from a claudew session.
        env.pop("NB_OPERATOR", None)
        env.pop("NB_UNATTENDED", None)
    r = subprocess.run(["python3", str(R/"scripts"/"google"/"gcalendar.py"), *args],
                       capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, _strip_ansi(r.stdout).strip(), _strip_ansi(r.stderr).strip()


def _prepare_block(title, start, end):
    """Validate a staged block server-side (times are the model's claim — sanity-check
    them here) and mint a one-use approval token. Local naive ISO throughout."""
    import secrets
    from datetime import datetime, timedelta
    title = (title or "").strip()[:120]
    if not title:
        return {"ok": False, "error": "block needs a title"}
    try:
        s = datetime.fromisoformat(start.strip())
        e = datetime.fromisoformat(end.strip())
    except (ValueError, TypeError, AttributeError):
        return {"ok": False, "error": "couldn't read the block times"}
    # the operator may emit a tz-aware time (trailing Z / offset). Coerce to local
    # naive so it (a) doesn't TypeError against a naive now, (b) lands at the right
    # wall-clock — gcalendar.py stamps the machine tz on the naive ISO we store.
    if s.tzinfo is not None:
        s = s.astimezone().replace(tzinfo=None)
    if e.tzinfo is not None:
        e = e.astimezone().replace(tzinfo=None)
    if e <= s:
        return {"ok": False, "error": "end must be after start"}
    if (e - s) > timedelta(hours=8):
        return {"ok": False, "error": "block longer than 8h — split it"}
    now = datetime.now()
    if s < now - timedelta(minutes=1):
        return {"ok": False, "error": "that start time is already past"}
    if s > now + timedelta(days=14):
        return {"ok": False, "error": "that's over two weeks out — double-check the date"}
    si, ei = s.isoformat(timespec="minutes"), e.isoformat(timespec="minutes")
    token = secrets.token_urlsafe(24)
    _CAL_TOKENS[token] = (title, si, ei, _CAL_ACCOUNT, time.time() + 300)
    return {"ok": True, "token": token, "title": title,
            "start": si, "end": ei, "account": _CAL_ACCOUNT}


def _load_json(path, default):
    """Defensive read — a missing/corrupt config degrades one section, not the whole UI."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


# ── task / memory readers ────────────────────────────────────────────────────
def fm(p):
    """Parse frontmatter + body from a task file."""
    t = p.read_text()
    d = {"_file": p.name}
    m = re.search(r"^---\n(.*?)\n---\n?(.*)", t, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                d[k.strip()] = v.strip()
        d["body"] = m.group(2).strip()
    return d


def tasks(folder):
    return [fm(p) for p in sorted(folder.glob("*.md"))] if folder.exists() else []


def brief_text():
    bs = sorted((R/"tasks").glob(".brief-*.md"))
    return bs[-1].read_text() if bs else "No brief yet — runs daily at 07:30, or run `nb brief`."


def wiki_pages():
    d = R/"wiki"/"pages"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.md")):
        f = fm(p)
        f["slug"] = p.stem
        f["links"] = re.findall(r"\[\[([^\]]+)\]\]", p.read_text())
        out.append(f)
    return out


def inbox_lines():
    p = R/"tasks"/"inbox.md"
    if not p.exists():
        return []
    return [l.strip()[6:].split("<!--")[0].strip()
            for l in p.read_text().splitlines() if l.startswith("- [ ]")]


# ── HUD data: slow sources behind a stale-while-refresh cache ────────────────
# /api/state is polled every few seconds; gcalendar/launchctl take seconds.
# cached() always returns instantly (last value or the default) and refreshes
# in a daemon thread at most once at a time per key.
_CACHE = {}          # key -> {"val", "ts", "busy"}
_CACHE_LOCK = threading.Lock()


def cached(key, ttl, fn, default):
    with _CACHE_LOCK:
        e = _CACHE.setdefault(key, {"val": default, "ts": 0.0, "busy": False})
        fresh = (time.time() - e["ts"]) < ttl
        if fresh or e["busy"]:
            return e["val"]
        e["busy"] = True

    def refresh():
        val = None
        try:
            val = fn()
        except Exception:
            pass                              # keep the previous value on any failure
        with _CACHE_LOCK:
            if val is not None:
                _CACHE[key]["val"] = val
            _CACHE[key]["ts"] = time.time()   # even failures wait a TTL before retrying
            _CACHE[key]["busy"] = False

    threading.Thread(target=refresh, daemon=True).start()
    return _CACHE[key]["val"]


def _agenda():
    """Today's events across all calendars — [] if Google auth isn't set up."""
    r = subprocess.run(
        ["python3", str(R/"scripts"/"google"/"gcalendar.py"), "agenda", "--all", "--days", "1"],
        capture_output=True, text=True, timeout=20, env=NB_ENV)
    out = []
    for line in (r.stdout or "").splitlines():
        m = re.match(r"^  (\S+)\s+(?:\[(\w+)\]\s+)?(.*?)(?:\s+@ (.*))?$", line)
        if m:
            out.append({"time": m.group(1), "account": m.group(2) or "",
                        "title": m.group(3).strip(), "loc": m.group(4) or ""})
    return out


# ── speech control: track speaker process groups so "stop talking" works ─────
_SPEAKERS = []


def _stop_speech():
    """Kill every in-flight speak.sh session (curl/edge/afplay/say die with it)."""
    import signal
    while _SPEAKERS:
        p = _SPEAKERS.pop()
        try:
            os.killpg(p.pid, signal.SIGTERM)   # start_new_session => pgid == pid
        except (ProcessLookupError, PermissionError, OSError):
            pass
    # sweep strays from other entry points (nb brief, watch) — audio players only
    for cmd in ("afplay", "say"):
        subprocess.run(["pkill", "-x", cmd], capture_output=True)


def _port_up(port, timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _systems():
    """Health of the moving parts: launchd jobs, voice, claude."""
    jobs = {}
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5)
        for line in (r.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[2].startswith("com.nathanbot."):
                name = parts[2].replace("com.nathanbot.", "")
                jobs[name] = {"running": parts[0] != "-", "last_exit": parts[1]}
    except Exception:
        pass
    logs = R/"tasks"/"logs"
    for name, meta in jobs.items():
        lp = logs/f"{name}.log"
        meta["last_run"] = int(lp.stat().st_mtime) if lp.exists() else None

    # a claude-capped event in the last hour = the subscription is rate-limited.
    # This watched "claude-fallback" until 2026-07-26 — the token bin/claudew
    # wrote back when it still had an Ollama fallback. claudew has written
    # "claude-capped" since that was removed, so this could never fire and the
    # one signal that says "your brain is unavailable" read ok permanently.
    capped = False
    try:
        tail = (R/"tasks"/".telemetry.jsonl").read_text().splitlines()[-200:]
        cutoff = time.time() - 3600
        for line in tail:
            if '"claude-capped"' in line:
                ev = json.loads(line)
                ts = time.mktime(time.strptime(ev["ts"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
                if ts > cutoff:
                    capped = True
    except Exception:
        pass
    return {
        "jobs": jobs,
        "voicebox": _port_up(17493),
        "claude": "capped" if capped else "ok",
        "checked": int(time.time()),
    }


def _telemetry_tail(n=30):
    p = R/"tasks"/".telemetry.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def state():
    accounts = _load_json(R/"config"/"accounts.json", {})
    return {
        "open": tasks(OPEN), "done": tasks(DONE),
        "brief": brief_text(),
        "wiki": wiki_pages(),
        "inbox": inbox_lines(),
        "permissions": _load_json(R/"config"/"permissions.json", {}),
        "chat": chat_history(),
        "accounts": accounts.get("accounts", {}) if isinstance(accounts, dict) else {},
        "agenda": cached("agenda", 300, _agenda, []),
        "systems": cached("systems", 60, _systems, {}),
        "telemetry": cached("telemetry", 5, _telemetry_tail, []),
    }


# ── chat history (atomic writes for the threaded server) ─────────────────────
CHAT = R/"tasks"/".chat.json"


def chat_history():
    if CHAT.exists():
        try:
            return json.loads(CHAT.read_text())
        except Exception:
            return []
    return []


def chat_save(h):
    tmp = CHAT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(h[-40:], indent=1))
    os.replace(tmp, CHAT)   # atomic; last-writer-wins is fine for one user


# ── say router: plain statements CAPTURE; only exact commands / plan / ? divert ─
SAY_COMMANDS = {
    "status": "status", "next": "next", "brief": "brief",
    "what's next": "next", "whats next": "next", "what next": "next",
    "what should i work on": "next", "what do i do": "next", "next up": "next",
    "catch me up": "brief", "what did i miss": "brief", "morning": "brief",
    "where am i": "status", "what's going on": "status", "whats going on": "status",
    "what's in flight": "status",
}
QUESTION_STARTS = ("what ", "what's", "whats", "how ", "why ", "when ", "who ",
                   "which ", "show me", "tell me", "is ", "are ", "can ", "should ")


def route_say(text):
    """Return (verb, args) for a `say` input. Default is capture."""
    low = text.strip().lower().rstrip("?!. ")

    if text.startswith("/"):
        parts = text[1:].split(None, 1)
        cmd = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        allowed = {"add", "brief", "triage", "audit", "groom", "tidy",
                   "evolve", "next", "status", "plan"}
        if cmd not in allowed:
            return ("unknown", cmd)
        return (cmd, [rest] if rest else [])

    # leading-verb: plan a goal
    if low.startswith(("plan ", "plan:")):
        goal = re.sub(r"^plan[: ]\s*", "", text.strip(), flags=re.I)
        return ("plan", [goal])

    # exact standalone read-command (won't hijack "check the build status")
    if low in SAY_COMMANDS:
        return (SAY_COMMANDS[low], [])

    # a question → point at nb discuss, capture nothing
    if text.strip().endswith("?") or low.startswith(QUESTION_STARTS):
        return ("ask", None)

    # default: capture it
    return ("add", [text])


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        # headless: the dashboard was retired. Static serving is disabled in do_GET;
        # this directory is just a harmless placeholder for the base class.
        super().__init__(*a, directory=str(R/"server"), **k)

    def end_headers(self):
        # never let WKWebView (Dock app) or a browser cache the UI — otherwise a
        # code update silently keeps showing the old page until a manual reload
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    # Only the local UI may talk to the API. Blocks cross-origin "simple requests"
    # from arbitrary websites and DNS-rebinding (Host must be a local literal).
    _OK_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}", "127.0.0.1", "localhost"}

    def _local_ok(self):
        if (self.headers.get("Host") or "") not in self._OK_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin:
            try:
                oh = urllib.parse.urlparse(origin).netloc
            except Exception:
                return False
            if oh not in self._OK_HOSTS:
                return False
        return True

    def do_GET(self):
        try:
            if self.path == "/api/state":
                if not self._local_ok():
                    return self._json({"ok": False, "error": "forbidden"}, 403)
                return self._json(state())
            if urllib.parse.urlparse(self.path).path == "/api/miclog":
                # mic diagnostics from the client — appends one line to
                # tasks/logs/mic.log so failures are readable.
                # The Host/Origin check is not optional here even though this only
                # writes a log: it was the one endpoint without it, so any page
                # the owner visited could <img src> arbitrary lines into that file.
                if not self._local_ok():
                    return self._json({"ok": False, "error": "forbidden"}, 403)
                import time as _t
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                msg = (q.get("m", [""])[0])[:400]
                try:
                    lf = R / "tasks" / "logs" / "mic.log"
                    lf.parent.mkdir(parents=True, exist_ok=True)
                    with open(lf, "a") as fh:
                        fh.write(_t.strftime("%H:%M:%S ") + msg + "\n")
                except Exception:
                    pass
                return self._json({"ok": True})
            # headless API — the dashboard was retired; talk to nathanbot on Telegram.
            body = b"nathanbot headless API - talk to me on Telegram."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        except Exception as e:                      # noqa: BLE001 — never hang the browser
            try:
                return self._json({"ok": False, "error": str(e)[:300]}, 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            return self._post()
        except subprocess.TimeoutExpired:
            return self._json({"ok": True, "isError": True,
                               "reply": "That took too long and timed out."})
        except Exception as e:                      # noqa: BLE001 — always answer JSON
            return self._json({"ok": False, "error": str(e)[:300]}, 500)

    def _post(self):
        if not self._local_ok():
            return self._json({"ok": False, "error": "forbidden"}, 403)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"ok": False, "error": "bad request body"}, 400)
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/add":
            if not body.get("text"):
                return self._json({"ok": False, "error": "empty"}, 400)
            nb("add", body["text"], timeout=30)
            return self._json({"ok": True})

        if path == "/api/transcribe":
            # transcribe audio the CLIENT recorded (Dock app: WKWebView getUserMedia
            # -> MediaRecorder -> base64). Mic access happens in the app process,
            # where macOS TCC can actually prompt; the server just runs whisper on
            # the uploaded bytes and never touches the microphone itself.
            import base64, tempfile
            b64 = body.get("audio") or ""
            mime = (body.get("mime") or "").lower()
            if not b64:
                return self._json({"ok": False, "error": "no audio"}, 400)
            ext = ".mp4" if "mp4" in mime else ".webm" if "webm" in mime else ".ogg" if "ogg" in mime else ".wav"
            try:
                raw = base64.b64decode(b64)
            except Exception:
                return self._json({"ok": False, "error": "bad audio encoding"}, 400)
            tmp = tempfile.mktemp(suffix=ext, dir=tempfile.gettempdir())
            try:
                with open(tmp, "wb") as fh:
                    fh.write(raw)
                r = subprocess.run(
                    ["python3", str(R/"scripts"/"voice"/"jarvis.py"), "stt", tmp],
                    capture_output=True, text=True, timeout=60, env=NB_ENV)
                text = _strip_ansi(r.stdout).strip().splitlines()[-1] if r.stdout.strip() else ""
                if r.returncode == 0 and text:
                    return self._json({"ok": True, "text": text})
                return self._json({"ok": False, "error": "Didn't catch that — try again."})
            except subprocess.TimeoutExpired:
                return self._json({"ok": False, "error": "transcription timed out"})
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass

        if path == "/api/listen":
            # legacy server-side recording (pvrecorder). Only works when the server
            # process itself holds a mic grant — the Dock app now records client-side
            # via /api/transcribe instead. Kept for the `nb jarvis` Terminal path.
            try:
                r = subprocess.run(
                    ["python3", str(R/"scripts"/"voice"/"jarvis.py"), "capture"],
                    capture_output=True, text=True, timeout=40, env=NB_ENV)
                text = _strip_ansi(r.stdout).strip().splitlines()[-1] if r.stdout.strip() else ""
                if r.returncode == 0 and text:
                    return self._json({"ok": True, "text": text})
                return self._json({"ok": False,
                                   "error": "mic unavailable — run 'nb jarvis once' in Terminal once to grant the microphone"})
            except subprocess.TimeoutExpired:
                return self._json({"ok": False, "error": "listening timed out"})

        if path == "/api/speak":
            # fire-and-forget: speak text in the Jarvis voice (speak.sh chain).
            # New speech interrupts old — overlapping voices are worse than a cut-off.
            t = (body.get("text") or "").strip()
            if t:
                _stop_speech()
                # start_new_session: audio must outlive whoever kills our process
                # group, and gives us a clean process group to stop on demand
                p = subprocess.Popen([str(R/"scripts"/"speak.sh"), t], env=NB_ENV,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                _SPEAKERS.append(p)
            return self._json({"ok": True})

        if path == "/api/speak/stop":
            _stop_speech()
            return self._json({"ok": True})

        if path == "/api/status":
            # validate: status is one of ours, never raw client text into the file
            new = body.get("status")
            if new not in {"ready", "blocked", "needs-decision", "done", "failed",
                           "looks-done"}:
                return self._json({"ok": False, "error": "bad status"}, 400)
            for p in OPEN.glob("*.md"):
                if fm(p).get("id") == body.get("id"):
                    t = re.sub(r"^status: .*$", f"status: {new}",
                               p.read_text(), count=1, flags=re.M)
                    p.write_text(t)
                    nb("_logdecision", str(p), new, timeout=30)
                    if new == "done":
                        DONE.mkdir(exist_ok=True)
                        p.rename(DONE/p.name)
                    return self._json({"ok": True})
            return self._json({"ok": False, "error": "not found"}, 404)

        if path == "/api/say":
            text = (body.get("text") or "").strip()
            if not text:
                return self._json({"ok": False, "error": "empty"}, 400)
            verb, args = route_say(text)

            if verb == "unknown":
                return self._json({"ok": False, "output": f"unknown command: /{args}"}, 400)
            if verb == "ask":
                return self._json({"ok": True, "verb": "ask",
                                   "output": "That's a question, not a task. Ask it in **Chat** for a "
                                             "full-context answer, or run `nb discuss` in a terminal.\n\n"
                                             "(Captured nothing — rephrase as a statement to add a task.)"})
            if verb == "add":
                nb("add", args[0], timeout=30)
                return self._json({"ok": True, "verb": "add", "output": f"Captured: {args[0]}"})

            # read/plan commands — may be slow, run in this (threaded) request
            out, _rc = nb(verb, *args, timeout=900 if verb == "plan" else 300)
            return self._json({"ok": True, "verb": verb, "output": out})

        if path == "/api/chat":
            msg = (body.get("text") or "").strip()
            if not msg:
                return self._json({"ok": False, "error": "empty"}, 400)
            hist = chat_history()
            convo = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in hist[-10:])
            prompt = build_operator_prompt(str(R), convo, msg, channel="chat")
            # Operator toolset: the nb CLI + the gmail script (which itself enforces
            # draft-not-send) + read/edit/web. Nothing else can run. NB_OPERATOR=1
            # hard-blocks the dangerous nb subcommands (run, tidy --apply, sync, evolve).
            # The operator ingests untrusted content (email/web), so the secrets vault is
            # hard-denied — a prompt injection can't read keys to exfiltrate via WebFetch.
            home = os.path.expanduser("~")
            # claudew wraps CLAUDE_BIN: same CLI, argv passed through unchanged so
            # the tool scoping below holds; it reports a usage cap explicitly
            chat_env = {**NB_ENV, "NB_OPERATOR": "1", "NB_CLAUDE_BIN": CLAUDE_BIN,
                        "NB_JOB": "chat"}
            argv = [str(R/"bin"/"claudew"), "-p", prompt,
                    "--model", chat_model(),
                    # only when set to a level the CLI accepts (see chat_effort)
                    *(["--effort", chat_effort()] if chat_effort() else []),
                    "--permission-mode", "acceptEdits",
                    # Both lists live in scripts/voice/prompt.py, shared with the
                    # voice daemon so the two channels cannot diverge. Enumerated
                    # nb verbs, never Bash(<nb>:*) — see the note there.
                    "--allowedTools", *operator_allowed_tools(str(R)),
                    "--disallowedTools", *operator_denied_tools(str(R)),
                    # the career specialist's source of truth lives outside the repo
                    *[a for d in operator_add_dirs(str(R)) for a in ("--add-dir", d)]]
            try:
                # cwd in the repo so the operator discovers .claude/agents/* (the specialists)
                r = subprocess.run(argv, capture_output=True, text=True, timeout=900,
                                   env=chat_env, cwd=str(R))
            except subprocess.TimeoutExpired:
                return self._json({"ok": True, "isError": True,
                                   "reply": "That took too long and timed out. Try a shorter ask."})
            out = _strip_ansi(r.stdout).strip()
            if r.returncode != 0 or not out:
                # surface the error but DON'T persist it as an answer
                return self._json({"ok": True, "isError": True,
                                   "reply": "Something went wrong reaching Claude — not saved.",
                                   "error": _strip_ansi(r.stderr).strip()[:800]})
            # did the operator stage a send? strip the marker, read the real draft,
            # and hand the UI an approval card. The operator cannot send — only the
            # card's [Approve & Send] click (a POST it can't make) does.
            send_request = None
            mk = _SEND_MARKER.search(out)
            if mk:
                out = _SEND_MARKER.sub("", out).strip()
                prep = _prepare_send(mk.group(1))
                send_request = prep if prep.get("ok") else None
                if not prep.get("ok"):
                    out = (out + f"\n\n(Couldn't stage the send: {prep.get('error')})").strip()
            # did the operator stage one or more calendar blocks? each becomes its own
            # Approve card. The operator is fused out of gcalendar writes — only the tap commits.
            cal_requests = []
            for m in _CAL_MARKER.finditer(out):
                prep = _prepare_block(m.group("title"), m.group("start"), m.group("end"))
                if prep.get("ok"):
                    cal_requests.append(prep)
                else:
                    out = (out + f"\n\n(Couldn't stage that block: {prep.get('error')})").strip()
            out = _CAL_MARKER.sub("", out).strip()
            hist += [{"role": "nathan", "text": msg}, {"role": "nathanbot", "text": out}]
            chat_save(hist)
            resp = {"ok": True, "reply": out}
            if send_request:
                resp["send_request"] = send_request
            if cal_requests:
                resp["cal_requests"] = cal_requests
            return self._json(resp)

        if path == "/api/mail/prepare":
            # the owner's browser asks to stage a send. POST-only, so the operator
            # (no POST tool) can never reach this. Returns TRUE recipient + a token.
            return self._json(_prepare_send(body.get("to")))

        if path == "/api/mail/send":
            # the actual send — fires ONLY on the owner's click, with a valid one-use
            # token. Runs gmail.py WITHOUT NB_OPERATOR (his approved act, not the model's).
            token = body.get("token", "")
            entry = _SEND_TOKENS.pop(token, None)
            if not entry:
                return self._json({"ok": False, "error": "expired or invalid approval — re-open the draft"}, 400)
            draft_id, account, expiry = entry
            if time.time() > expiry:
                return self._json({"ok": False, "error": "approval expired — re-open the draft"}, 400)
            rc, out, err = _gmail(account, "send", draft_id, "--yes", account,
                                  timeout=30, drop_operator=True)
            if rc != 0:
                return self._json({"ok": False, "error": (err or out or "send failed")[:300]})
            return self._json({"ok": True, "sent": True})

        if path == "/api/cal/commit":
            # writes a calendar block — fires ONLY on the owner's tap, with a valid one-use
            # token. Runs gcalendar.py WITHOUT NB_OPERATOR (his approved act, not the model's).
            token = body.get("token", "")
            entry = _CAL_TOKENS.pop(token, None)
            if not entry:
                return self._json({"ok": False, "error": "expired or invalid approval — ask again"}, 400)
            title, start, end, account, expiry = entry
            if time.time() > expiry:
                return self._json({"ok": False, "error": "approval expired — ask again"}, 400)
            rc, out, err = _gcal("--account", account, "create", "--title", title,
                                 "--start", start, "--end", end, timeout=30, drop_operator=True)
            if rc != 0:
                return self._json({"ok": False, "error": (err or out or "calendar write failed")[:300]})
            return self._json({"ok": True, "created": True, "title": title, "start": start})

        if path == "/api/chat/clear":
            chat_save([])
            return self._json({"ok": True})

        if path == "/api/run":
            cmd = body.get("cmd")
            if cmd not in ("brief", "triage", "audit", "groom", "tidy", "evolve"):
                return self._json({"ok": False, "error": "not allowed"}, 400)
            out, _rc = nb(cmd, timeout=600)
            return self._json({"ok": True, "output": out})

        return self._json({"ok": False}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    # Threaded so one slow chat/run can't freeze state polling or other requests.
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    server.daemon_threads = True
    print(f"nathanbot UI → http://127.0.0.1:{PORT}")
    print("(local only — not reachable from the network)")
    server.serve_forever()
