#!/usr/bin/env python3
"""jarvis.py — nathanbot's hands-free voice loop.

  say "Jarvis" -> chime -> ask -> it acts -> it answers aloud.

Pipeline (all on-device): Porcupine "Jarvis" wake word -> record (energy VAD) ->
faster-whisper STT -> the nathanbot operator (claude -p, NB_OPERATOR=1, scoped tools) ->
speak.sh TTS. Reuses server/server.py's operator pattern and the shared prompt loader.

  nb jarvis start [--wake-test]   foreground wake-word loop (what launchd runs)
  nb jarvis once                  one turn, no wake word (also triggers the mic grant)
  nb jarvis text "what's next"    operator + speak, NO audio in (fast test)
  nb jarvis stt <file.wav>        transcribe a wav and print it
  nb jarvis record-test           record one utterance, play it back
  nb jarvis status | stop         launchd control
"""
import os
import sys

# ── self-heal the interpreter: re-exec into the voice venv if we're not in it ──
_VENV_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python")
# NB: compare unresolved paths — a venv's bin/python symlinks to the base interpreter,
# so realpath() would match and wrongly skip the re-exec (leaving us without the venv's
# site-packages). abspath keeps them distinct.
if os.path.exists(_VENV_PY) and os.path.abspath(sys.executable) != _VENV_PY:
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

import argparse
import re
import struct
import subprocess
import tempfile
import time
import wave
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # scripts/voice -> repo root
NB = os.path.join(ROOT, "bin", "nb")
SPEAK = os.path.join(ROOT, "scripts", "speak.sh")
PICO_KEY_FILE = os.path.expanduser("~/.secrets/picovoice/access_key")
LOG = os.path.join(ROOT, "tasks", "logs", "jarvis.log")
CHIME = "/System/Library/Sounds/Ping.aiff"

SAMPLE_RATE = 16000
WHISPER_MODEL = os.environ.get("NB_WHISPER_MODEL", "base.en")
BAIL = {"never mind", "nevermind", "cancel", "stop", "forget it", "quit"}
HALLUC = {"you", "thank you.", "thanks for watching!", "[blank_audio]", ".", ". .", "bye."}

sys.path.insert(0, HERE)
from prompt import build_operator_prompt  # noqa: E402

CONVO = deque(maxlen=6)


# ── claude / env resolution (mirrors server/server.py:13-34) ──────────────────────
def _which_claude():
    import shutil
    for c in (shutil.which("claude"),
              os.path.expanduser("~/.local/bin/claude"),
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude",
              os.path.expanduser("~/.claude/local/claude")):
        if c and os.path.exists(c):
            return c
    return "claude"


CLAUDE_BIN = _which_claude()
HARDENED_PATH = os.pathsep.join([
    os.path.dirname(CLAUDE_BIN), "/opt/homebrew/bin", "/usr/local/bin",
    "/usr/bin", "/bin", "/usr/sbin", "/sbin", os.path.expanduser("~/.local/bin"),
])
ENV = {**os.environ, "PATH": HARDENED_PATH, "NB_OPERATOR": "1",
       "NB_CLAUDE_BIN": CLAUDE_BIN}   # claudew resolves the real CLI from this


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s or "")


# ── audio helpers ─────────────────────────────────────────────────────────────
def _rms(pcm):
    if not pcm:
        return 0.0
    return (sum(s * s for s in pcm) / len(pcm)) ** 0.5


def chime():
    try:
        subprocess.run(["afplay", CHIME], env=ENV, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass


def write_wav(frames, path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(struct.pack("<%dh" % len(frames), *frames))


def calibrate(recorder, ms=500):
    frame_ms = recorder.frame_length / SAMPLE_RATE * 1000.0
    vals = [_rms(recorder.read()) for _ in range(max(1, int(ms / frame_ms)))]
    floor = sorted(vals)[len(vals) // 2]
    return max(floor * 3.0, 350.0)


def record_utterance(recorder, thresh, max_ms=15000, silence_ms=1200, pre_ms=3000):
    """Read from an already-started recorder until trailing silence. Returns int16 list."""
    frame_ms = recorder.frame_length / SAMPLE_RATE * 1000.0
    frames, started, silence, elapsed, pre = [], False, 0.0, 0.0, 0.0
    while True:
        pcm = recorder.read()
        loud = _rms(pcm) > thresh
        elapsed += frame_ms
        if not started:
            pre += frame_ms
            if loud:
                started = True
                frames.extend(pcm)
            elif pre > pre_ms:
                return []                       # nobody spoke
        else:
            frames.extend(pcm)
            silence = 0.0 if loud else silence + frame_ms
            if silence > silence_ms or elapsed > max_ms:
                break
    return frames


def drain(recorder, ms=300):
    """Discard buffered frames (e.g. our own TTS) before listening again."""
    frame_ms = recorder.frame_length / SAMPLE_RATE * 1000.0
    for _ in range(int(ms / frame_ms)):
        recorder.read()


# ── STT ───────────────────────────────────────────────────────────────────────
_model = None


def stt_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        log(f"loading whisper '{WHISPER_MODEL}' (first run downloads it)…")
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(path):
    segs, _ = stt_model().transcribe(path, language="en", beam_size=1)
    return " ".join(s.text for s in segs).strip()


def is_junk(text):
    t = text.strip().lower()
    return len(t) < 2 or t in BAIL or t in HALLUC


# ── brain + voice ─────────────────────────────────────────────────────────────
def speak(text):
    if not text:
        return
    try:
        # generous cap: long replies via Voicebox can take a while, but a wedged
        # audio path must never freeze the wake loop forever
        subprocess.run([SPEAK, text], env=ENV, timeout=120,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        log("speak timed out — continuing")


def ask_operator(text):
    prompt = build_operator_prompt(ROOT, "\n".join(CONVO), text, channel="voice")
    home = os.path.expanduser("~")
    # claudew: same CLI, auto-falls back to the local brain when usage caps
    argv = [os.path.join(ROOT, "bin", "claudew"), "-p", prompt, "--permission-mode", "acceptEdits",
            "--allowedTools", "Read", "Grep", "Glob", "Edit", "Write", "WebSearch", "WebFetch",
            f"Bash({NB}:*)", f"Bash(python3 {ROOT}/scripts/google/gmail.py:*)",
            f"Bash(python3 {ROOT}/scripts/google/gcalendar.py:*)",  # solo events only (fused)
            "--disallowedTools",
            f"Read({home}/.secrets/**)", f"Grep({home}/.secrets/**)",
            f"Glob({home}/.secrets/**)", f"Edit({home}/.secrets/**)",
            f"Write({home}/.secrets/**)"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=900, env=ENV)
    except subprocess.TimeoutExpired:
        return "That took too long, sir."
    out = _strip_ansi(r.stdout).strip()
    if r.returncode != 0 or not out:
        log(f"operator error rc={r.returncode}: {_strip_ansi(r.stderr)[:300]}")
        return "Something went wrong reaching Claude."
    CONVO.append(f"NATHAN: {text}")
    CONVO.append(f"NATHANBOT: {out}")
    return out


def handle_utterance(frames):
    """frames -> transcript -> (guard) -> operator -> speak. Best-effort."""
    if not frames:
        return
    wav = tempfile.mktemp(suffix=".wav", dir=tempfile.gettempdir())
    try:
        write_wav(frames, wav)
        try:
            text = transcribe(wav)
        finally:
            try:
                os.remove(wav)          # never keep the audio around
            except OSError:
                pass
    except Exception as e:
        log(f"stt failed: {e}")
        return
    log(f"heard: {text!r}")
    if is_junk(text):
        return
    # long op: kick off, speak a filler if it's slow
    result = {}

    import threading

    def _work():
        result["reply"] = ask_operator(text)

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(2.5)
    if t.is_alive():
        speak("One moment.")
        t.join(900)
    reply = result.get("reply", "")
    log(f"reply: {reply!r}")
    speak(reply)


# ── modes ─────────────────────────────────────────────────────────────────────
def _boot_greeting():
    h = int(time.strftime("%H"))
    part = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    speak(f"Good {part}, sir. Systems online and at your service.")


def load_key():
    if not os.path.exists(PICO_KEY_FILE):
        return None
    return open(PICO_KEY_FILE).read().strip()


def cmd_start(args):
    key = load_key()
    if not key:
        log("no Picovoice key at ~/.secrets/picovoice/access_key — "
            "wake word disabled. Use `nb jarvis once` or a push-to-talk hotkey.")
        return 1
    import pvporcupine
    from pvrecorder import PvRecorder
    porcupine = pvporcupine.create(access_key=key, keywords=["jarvis"])
    mic = int(os.environ.get("NB_MIC_INDEX", "-1"))
    recorder = PvRecorder(frame_length=porcupine.frame_length, device_index=mic)
    recorder.start()
    thresh = calibrate(recorder)
    log(f"jarvis listening — say 'Jarvis' (vad thresh {thresh:.0f})")
    _boot_greeting()
    try:
        while True:
            pcm = recorder.read()
            if porcupine.process(pcm) >= 0:
                if args.wake_test:
                    print("WAKE", flush=True)
                    continue
                try:
                    chime()
                    frames = record_utterance(recorder, thresh)
                    handle_utterance(frames)
                except Exception as e:
                    log(f"turn error: {e}")
                    speak("Sorry, something glitched.")
                drain(recorder)
    except KeyboardInterrupt:
        pass
    finally:
        recorder.delete()
        porcupine.delete()
    return 0


def cmd_once(args):
    from pvrecorder import PvRecorder
    recorder = PvRecorder(frame_length=512, device_index=int(os.environ.get("NB_MIC_INDEX", "-1")))
    recorder.start()
    try:
        thresh = calibrate(recorder)
        chime()
        log("listening (once)…")
        frames = record_utterance(recorder, thresh)
    finally:
        recorder.delete()
    if not frames:
        speak("I didn't catch anything.")
        return 0
    handle_utterance(frames)
    return 0


def cmd_text(args):
    reply = ask_operator(" ".join(args.words))
    print(reply)
    speak(reply)
    return 0


def cmd_stt(args):
    print(transcribe(args.wav))
    return 0


def cmd_capture(args):
    """Record one utterance -> print ONLY the transcript (for /api/listen). No speak."""
    from pvrecorder import PvRecorder
    recorder = PvRecorder(frame_length=512, device_index=int(os.environ.get("NB_MIC_INDEX", "-1")))
    recorder.start()
    try:
        thresh = calibrate(recorder)
        chime()
        frames = record_utterance(recorder, thresh)
    finally:
        recorder.delete()
    if not frames:
        return 1
    wav = tempfile.mktemp(suffix=".wav", dir=tempfile.gettempdir())
    try:
        write_wav(frames, wav)
        text = transcribe(wav)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
    if is_junk(text):
        return 1
    print(text)
    return 0


def cmd_record_test(args):
    from pvrecorder import PvRecorder
    recorder = PvRecorder(frame_length=512, device_index=int(os.environ.get("NB_MIC_INDEX", "-1")))
    recorder.start()
    try:
        thresh = calibrate(recorder)
        chime()
        print(f"speak now (vad thresh {thresh:.0f})…")
        frames = record_utterance(recorder, thresh)
    finally:
        recorder.delete()
    if not frames:
        print("nothing recorded")
        return 1
    wav = tempfile.mktemp(suffix=".wav")
    write_wav(frames, wav)
    print(f"recorded {len(frames)/SAMPLE_RATE:.1f}s -> {wav}; playing back…")
    subprocess.run(["afplay", wav])
    return 0


def _loaded(label):
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    return any(label in ln for ln in r.stdout.splitlines())


def cmd_status(args):
    import urllib.request

    def ok(b):
        return "\033[32m✓\033[0m" if b else "\033[31m✗\033[0m"

    # Voicebox TTS server
    vb = False
    try:
        urllib.request.urlopen("http://127.0.0.1:17493/health", timeout=2)
        vb = True
    except Exception:
        vb = False
    # STT
    try:
        import faster_whisper  # noqa: F401
        stt = True
    except Exception:
        stt = False
    key = os.path.exists(PICO_KEY_FILE)
    # speak.sh defaults to the "Jarvis" Voicebox profile when the server is up
    prof = os.environ.get("NB_VOICEBOX_PROFILE") or ("Jarvis (default)" if vb else "macOS say (Voicebox down)")

    print("nathanbot voice — systems check")
    print(f"  {ok(vb)}  Voicebox TTS server (:17493)      {'up' if vb else 'down — nb schedule install-voicebox'}")
    print(f"  {ok(_loaded('com.nathanbot.voicebox'))}  Voicebox daemon (always-on)")
    print(f"  {ok(stt)}  Speech-to-text (faster-whisper)")
    print(f"  {ok(key)}  Wake word 'Jarvis' (Picovoice key)  {'ready' if key else 'MISSING ~/.secrets/picovoice/access_key'}")
    print(f"  {ok(_loaded('com.nathanbot.jarvis'))}  Hands-free daemon (nb schedule install-jarvis)")
    print(f"  ·  Reply voice profile: {prof}")
    print("  Test:  nb jarvis text \"what's next\"   |   push-to-talk:  nb jarvis once")
    return 0


def cmd_stop(args):
    plist = os.path.expanduser("~/Library/LaunchAgents/com.nathanbot.jarvis.plist")
    subprocess.run(["launchctl", "unload", plist])
    print("jarvis daemon stopped")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="nb jarvis")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("start"); p.add_argument("--wake-test", action="store_true")
    sub.add_parser("once")
    p = sub.add_parser("text"); p.add_argument("words", nargs="+")
    p = sub.add_parser("stt"); p.add_argument("wav")
    sub.add_parser("capture")
    sub.add_parser("record-test")
    sub.add_parser("status")
    sub.add_parser("stop")
    args = ap.parse_args()
    fn = {"start": cmd_start, "once": cmd_once, "text": cmd_text, "stt": cmd_stt,
          "capture": cmd_capture, "record-test": cmd_record_test,
          "status": cmd_status, "stop": cmd_stop}.get(args.cmd)
    if not fn:
        ap.print_help()
        return 1
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
