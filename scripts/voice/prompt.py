"""Shared operator-prompt builder — ONE source of truth for both the dashboard
(server/server.py) and the voice daemon (scripts/voice/jarvis.py), so the two stay in
lockstep. The template lives in prompts/operator.md."""
import os
from datetime import datetime

# Voice replies are heard, not read — keep them to a spoken sentence, no markup.
_VOICE_NOTE = """
VOICE CHANNEL — the owner is listening, not reading. Reply in ONE spoken sentence (two only if
truly needed). No markdown, lists, code, or URLs — say them in plain words. A light, dry butler
tone fits ("Done." / "On it."). Address him as "the owner," never "sir." If you need his
go-ahead, ask it as one spoken question.
"""

# Chat replies are shown AND read aloud — they must sound human when spoken.
_CHAT_NOTE = """
CHAT CHANNEL — your reply appears on screen AND is read aloud, so write for the ear:
plain conversational sentences a butler would actually say. Lead with the answer. HARD
RULES: no markdown (**, `, #, bullets, tables), no arrows or symbols, no bare file paths,
line numbers, or task IDs — say "the job-search decision" not "t-0003", "the triage code"
not "bin/nb:75". Keep it to 1-3 short sentences unless the owner asks for detail. Offer next
steps as a natural question, not a menu of quoted commands.
"""

_NOTES = {"chat": _CHAT_NOTE, "voice": _VOICE_NOTE}


def _bounded(path, cap):
    """Read a curated memory file, capped (Hermes model: memory the agent IS, not
    retrieves). Bounded so it's always-affordable to inject into every call."""
    try:
        with open(path) as f:
            return f.read().strip()[:cap]
    except OSError:
        return ""


def build_operator_prompt(root, convo, msg, channel="chat"):
    with open(os.path.join(root, "prompts", "operator.md")) as f:
        tpl = f.read()
    # Hermes-style always-loaded snapshot: who the owner is + how the system works,
    # injected into EVERY call so he never re-explains himself. USER = the LIVE
    # bounded profile (shared-memory/OVERVIEW.md, which `nb learn` keeps current —
    # so the injected memory stays fresh with zero extra maintenance); MEMORY =
    # the stable system self-knowledge (hermes/MEMORY.md).
    user = (_bounded(os.path.join(root, "shared-memory", "OVERVIEW.md"), 2600)
            or _bounded(os.path.join(root, "hermes", "USER.md"), 1600)
            or "(profile unavailable)")
    memory = _bounded(os.path.join(root, "hermes", "MEMORY.md"), 2400) or "(system memory unavailable)"
    # Current local wall-clock, so the operator can resolve "this afternoon" / "in 2h"
    # into concrete ISO datetimes for calendar blocks. Local naive ISO — gcalendar.py
    # stamps the machine timezone on it, so no offset math needed here.
    n = datetime.now().astimezone()
    now_str = (f"{n.strftime('%A %Y-%m-%d %H:%M %Z')}  "
               f"(ISO local now = {n.strftime('%Y-%m-%dT%H:%M')})")
    return (tpl
            .replace("{{ROOT}}", root)
            .replace("{{USER}}", user)
            .replace("{{MEMORY}}", memory)
            .replace("{{NOW}}", now_str)
            .replace("{{CONVO}}", convo or "(none)")
            .replace("{{MSG}}", msg)
            .replace("{{CHANNEL_NOTE}}", _NOTES.get(channel, "")))
