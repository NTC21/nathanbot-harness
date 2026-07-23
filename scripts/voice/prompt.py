"""Shared operator-prompt builder — ONE source of truth for both the dashboard
(ui/server.py) and the voice daemon (scripts/voice/jarvis.py), so the two stay in
lockstep. The template lives in prompts/operator.md."""
import os

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


def build_operator_prompt(root, convo, msg, channel="chat"):
    with open(os.path.join(root, "prompts", "operator.md")) as f:
        tpl = f.read()
    return (tpl
            .replace("{{ROOT}}", root)
            .replace("{{CONVO}}", convo or "(none)")
            .replace("{{MSG}}", msg)
            .replace("{{CHANNEL_NOTE}}", _NOTES.get(channel, "")))
