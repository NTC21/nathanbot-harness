#!/usr/bin/env python3
"""nathanbot UI — local server. No build step, no deps beyond stdlib.
Serves the dashboard and a small JSON API over the real task/memory files.
"""
import json, os, re, subprocess, pathlib, http.server, urllib.parse

R = pathlib.Path(__file__).resolve().parents[1]
OPEN, DONE, ARCH = R/"tasks"/"open", R/"tasks"/"done", R/"tasks"/"archive"
PORT = int(os.environ.get("NB_UI_PORT", "7777"))
NB = str(R/"bin"/"nb")


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

# nb shells out to `claude` via bare `command -v claude`, which only resolves if
# PATH contains it. Pass a hardened PATH to every nb subprocess so it works even
# when the server is launched outside the LaunchAgent (which sets PATH itself).
_HARDENED_PATH = os.pathsep.join([
    os.path.dirname(CLAUDE_BIN), "/opt/homebrew/bin", "/usr/local/bin",
    "/usr/bin", "/bin", "/usr/sbin", "/sbin", os.path.expanduser("~/.local/bin"),
])
NB_ENV = {**os.environ, "PATH": _HARDENED_PATH}


def nb(*args, timeout=600):
    """Run an nb subcommand with the hardened env; return cleaned stdout+stderr."""
    r = subprocess.run([NB, *args], capture_output=True, text=True,
                       timeout=timeout, env=NB_ENV)
    return re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or "")), r.returncode


def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s or "")


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
        super().__init__(*a, directory=str(R/"ui"/"dist"), **k)

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/state":
            return self._json(state())
        # SPA: unknown non-asset paths fall back to index.html
        p = urllib.parse.urlparse(self.path).path
        if p != "/" and not (R/"ui"/"dist"/p.lstrip("/")).exists():
            self.path = "/"
        return super().do_GET()

    def do_POST(self):
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

        if path == "/api/status":
            for p in OPEN.glob("*.md"):
                if fm(p).get("id") == body.get("id"):
                    t = re.sub(r"^status: .*$", f"status: {body['status']}",
                               p.read_text(), count=1, flags=re.M)
                    p.write_text(t)
                    nb("_logdecision", str(p), body["status"], timeout=30)
                    if body["status"] == "done":
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
            prompt = f"""You are nathanbot — the owner's operator (their "Jarvis") in the dashboard.
You do not just answer; you ACT on intent. The owner should never have to name a command.

FIRST load their context (don't dump it back at them):
- {R}/shared-memory/OVERVIEW.md
- {R}/AGENTS.md   (routing + hard rules)
- {R}/config/accounts.json   (email identities)
- {R}/config/permissions.json   (what you may do without asking)
- any {R}/wiki/pages/*.md the request actually needs (start at {R}/wiki/index.md)

TOOLS — use them; the nb CLI is at {R}/bin/nb :
- capture work:            {R}/bin/nb add "<task>"
- file inbox -> tasks:     {R}/bin/nb triage
- decompose a goal:        {R}/bin/nb plan "<goal>"
- see state:               {R}/bin/nb status  |  next  |  brief
- scaffold a NEW project:  {R}/bin/nb project new <name> --type <next|expo|python|node>
- maintenance (report):    {R}/bin/nb audit  |  tidy  |  groom
- read email subjects:     python3 {R}/scripts/google/gmail.py --account personal search "<query>"
- draft email (no send):   python3 {R}/scripts/google/gmail.py --account personal draft --to .. --subject .. --body ..
- read files, run read-only shell, search memory — freely.

ACT ON INTENT (do the thing, then say what you did):
- a statement of work / "remind me to X" / "I need to X"  -> capture it (nb add), then nb triage so it becomes a real task.
- "what should I do / what's up / where am I"              -> read state, answer concretely with the actual top items.
- "plan X" / "how do I build X"                            -> nb plan into tasks.
- "make/start a project X"                                 -> nb project new (infer type), report what got created.
- "clean up / what's messy"                               -> run tidy/audit in REPORT mode, summarize. Apply cleanup ONLY on their explicit yes.
- "check my email / what's in my inbox"                    -> read subjects (allowed), summarize. Reading bodies needs their yes.
- "draft an email to X"                                    -> draft it, show it. DO NOT send.
- a real question / "should we?"                           -> answer with full context and a real opinion, including disagreement.

SAFETY — hard rules, never cross unattended (the owner may be away):
- NEVER send/reply email, create or modify calendar events, push, merge, delete files or branches,
  or run anything destructive (tidy --apply, rm) without the owner's explicit yes IN THIS CHAT. Draft/propose and ask.
- Only the authorized sending identity in {R}/config/accounts.json may send. Never substitute another identity.
- Executing work against their real project code (nb run) is their call — tee it up, don't run it unattended.
- If you learn something durable about the owner, write it to memory per {R}/wiki/storage-policy.md.

RECENT CONVERSATION:
{convo or '(none)'}

OWNER: {msg}

Reply terse — no filler. Lead with what you DID (name the action), then what's next or one clear question."""
            try:
                r = subprocess.run([CLAUDE_BIN, "-p", prompt, "--permission-mode", "acceptEdits"],
                                   capture_output=True, text=True, timeout=900)
            except subprocess.TimeoutExpired:
                return self._json({"ok": True, "isError": True,
                                   "reply": "That took too long and timed out. Try a shorter ask."})
            out = _strip_ansi(r.stdout).strip()
            if r.returncode != 0 or not out:
                # surface the error but DON'T persist it as an answer
                return self._json({"ok": True, "isError": True,
                                   "reply": "Something went wrong reaching Claude — not saved.",
                                   "error": _strip_ansi(r.stderr).strip()[:800]})
            hist += [{"role": "user", "text": msg}, {"role": "nathanbot", "text": out}]
            chat_save(hist)
            return self._json({"ok": True, "reply": out})

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
