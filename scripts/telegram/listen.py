#!/usr/bin/env python3
"""nathanbot Telegram bridge — the two-way phone channel.

You text the bot from anywhere; it routes to the SAME operator the dashboard uses
(POST /api/chat, NB_OPERATOR-fused), and texts the reply back. Email-send approvals
arrive as inline [Approve] / [Cancel] buttons — tapping Approve fires the gated
send (POST /api/mail/send). Telegram holds messages ~24h server-side, so anything
you send while the Mac sleeps is processed when it wakes. No VPS, $0.

Secrets (in ~/.secrets/telegram/, dir 700, files 600):
  bot_token   the @BotFather token
  chat_id     YOUR numeric chat id — the ONLY id this bot answers (get it: --whoami)

  python3 listen.py            long-poll forever (the launchd job runs this)
  python3 listen.py --whoami   print the chat id of the next person who messages
  python3 listen.py --once     process one batch and exit (testing)
"""
import json, os, sys, time, urllib.request, urllib.parse, pathlib

SEC = pathlib.Path(os.path.expanduser("~/.secrets/telegram"))
STATE = pathlib.Path(__file__).resolve().parents[2] / "tasks" / ".tg-offset"
UI = os.environ.get("NB_UI_URL", "http://127.0.0.1:7777")


def _read(name):
    p = SEC / name
    return p.read_text().strip() if p.exists() else ""


TOKEN = _read("bot_token")
CHAT_ID = _read("chat_id")
API = f"https://api.telegram.org/bot{TOKEN}"


def tg(method, **params):
    """Call a Bot API method. Returns the 'result' or None on failure."""
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                   for k, v in params.items()}).encode()
    try:
        with urllib.request.urlopen(f"{API}/{method}", data=data, timeout=40) as r:
            j = json.load(r)
            return j.get("result") if j.get("ok") else None
    except Exception:
        return None


def ui_post(path, payload, timeout=900):
    try:
        req = urllib.request.Request(f"{UI}{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def send(text, buttons=None):
    kw = {"chat_id": CHAT_ID, "text": text[:4000], "disable_web_page_preview": True}
    if buttons:
        kw["reply_markup"] = {"inline_keyboard": buttons}
    tg("sendMessage", **kw)


# ── voice: you talk, it talks back (the Jarvis bit) ──────────────────────────
import base64, subprocess, tempfile  # noqa: E402

EDGE = os.path.expanduser("~/.local/bin/edge-tts")
VOICE = os.environ.get("NB_EDGE_VOICE", "en-GB-RyanNeural")   # British "Jarvis"


def transcribe_voice(file_id):
    """Telegram voice note -> text, via the server's whisper (/api/transcribe)."""
    meta = tg("getFile", file_id=file_id)
    if not meta:
        return ""
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{TOKEN}/{meta['file_path']}", timeout=30) as r:
            audio = r.read()
    except Exception:
        return ""
    res = ui_post("/api/transcribe", {"audio": base64.b64encode(audio).decode(), "mime": "audio/ogg"}, timeout=120)
    return (res.get("text") or "").strip() if res.get("ok") else ""


def synth_ogg(text):
    """text -> ogg/opus temp file (a real Telegram voice note). None on failure."""
    mp3 = tempfile.mktemp(suffix=".mp3")
    ogg = tempfile.mktemp(suffix=".ogg")
    try:
        subprocess.run([EDGE, "--voice", VOICE, "--text", text[:1400], "--write-media", mp3],
                       timeout=40, capture_output=True)
        if not (os.path.exists(mp3) and os.path.getsize(mp3)):
            return None
        subprocess.run(["ffmpeg", "-y", "-i", mp3, "-c:a", "libopus", "-b:a", "32k", ogg],
                       timeout=40, capture_output=True)
        return ogg if (os.path.exists(ogg) and os.path.getsize(ogg)) else None
    except Exception:
        return None
    finally:
        try:
            os.remove(mp3)
        except OSError:
            pass


def send_voice(text):
    """Speak `text` back as a voice note. Silent no-op if synthesis fails."""
    ogg = synth_ogg(text)
    if not ogg:
        return
    try:
        subprocess.run(["curl", "-sf", f"{API}/sendVoice",
                        "-F", f"chat_id={CHAT_ID}", "-F", f"voice=@{ogg}"],
                       timeout=40, capture_output=True)
    finally:
        try:
            os.remove(ogg)
        except OSError:
            pass


def _log(m):
    print(f"{int(time.time())} {m}", flush=True)


def handle_message(msg):
    # SECURITY: only ever answer the owner's chat id.
    cid = str(msg.get("chat", {}).get("id"))
    if cid != str(CHAT_ID):
        _log(f"ignored msg from chat {cid} (not owner)")
        return
    # voice note? transcribe it, and remember to reply in voice too.
    spoken = False
    voice = msg.get("voice") or msg.get("audio")
    if voice:
        tg("sendChatAction", chat_id=CHAT_ID, action="typing")
        text = transcribe_voice(voice["file_id"])
        spoken = True
        if not text:
            send("Couldn't make out that voice note — try again?")
            return
    else:
        text = (msg.get("text") or "").strip()
    if not text:
        return
    _log(f"recv{' (voice)' if spoken else ''}: {text[:60]}")
    tg("sendChatAction", chat_id=CHAT_ID, action="typing")
    ack = tg("sendMessage", chat_id=CHAT_ID, text="🤔 on it…")   # instant feedback; edited to the reply
    r = ui_post("/api/chat", {"text": text})
    reply = (r.get("reply") or "…").strip() if r.get("ok") else \
            f"(couldn't reach the brain: {r.get('error','error')})"
    _log(f"reply ok={r.get('ok')} len={len(reply)} spoken={spoken} send_request={bool(r.get('send_request'))}")
    # show the reply as text (prefix the heard transcript for voice, so you see what it caught)
    shown = (f"🎙 “{text}”\n\n{reply}" if spoken else reply)[:4000]
    ack_id = (ack or {}).get("message_id")
    if ack_id:
        tg("editMessageText", chat_id=CHAT_ID, message_id=ack_id, text=shown)
    else:
        send(shown)
    if spoken:                       # you talked -> it talks back
        send_voice(reply)
    sr = r.get("send_request")
    if sr and sr.get("token"):
        send(f"✉️ Send this?\nTo: {sr.get('to')}\nSubject: {sr.get('subject') or '(none)'}\n"
             f"From: {sr.get('from') or sr.get('account')}",
             buttons=[[{"text": "✅ Approve & Send", "callback_data": "send:" + sr["token"]},
                       {"text": "✖️ Cancel", "callback_data": "cancel"}]])


def handle_callback(cb):
    if str(cb.get("from", {}).get("id")) != str(CHAT_ID) and \
       str(cb.get("message", {}).get("chat", {}).get("id")) != str(CHAT_ID):
        return
    data = cb.get("data", "")
    cbid = cb.get("id")
    if data.startswith("send:"):
        res = ui_post("/api/mail/send", {"token": data[5:]}, timeout=60)
        msg = "✅ Sent" if res.get("ok") else f"Not sent — {res.get('error','failed')}"
        tg("answerCallbackQuery", callback_query_id=cbid, text=msg)
        send(msg)
    elif data == "cancel":
        tg("answerCallbackQuery", callback_query_id=cbid, text="Cancelled")
        send("Cancelled — draft kept, not sent.")


def _load_offset():
    try:
        return int(STATE.read_text().strip())
    except Exception:
        return 0


def _save_offset(n):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(str(n))
    except Exception:
        pass


def whoami():
    print("Message your bot now — waiting for the next update…", file=sys.stderr)
    while True:
        ups = tg("getUpdates", timeout=25, offset=_load_offset()) or []
        for u in ups:
            _save_offset(u["update_id"] + 1)
            m = u.get("message") or u.get("edited_message")
            if m:
                c = m.get("chat", {})
                print(f"chat_id: {c.get('id')}   name: {c.get('first_name','')} @{c.get('username','')}")
                print(f"\nSave it:  echo {c.get('id')} > ~/.secrets/telegram/chat_id && chmod 600 ~/.secrets/telegram/chat_id")
                return
        time.sleep(1)


def loop(once=False):
    while True:
        ups = tg("getUpdates", timeout=25, offset=_load_offset()) or []
        for u in ups:
            _save_offset(u["update_id"] + 1)
            if "message" in u:
                handle_message(u["message"])
            elif "callback_query" in u:
                handle_callback(u["callback_query"])
        if once:
            return
        if ups == []:
            time.sleep(1)


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("no bot token — create a bot via @BotFather, then:\n"
                 "  mkdir -p ~/.secrets/telegram && chmod 700 ~/.secrets/telegram\n"
                 "  printf '%s' '<TOKEN>' > ~/.secrets/telegram/bot_token && chmod 600 ~/.secrets/telegram/bot_token")
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--whoami":
        whoami()
    elif not CHAT_ID:
        sys.exit("no chat_id set — run:  python3 listen.py --whoami")
    elif arg == "--once":
        loop(once=True)
    else:
        loop()
