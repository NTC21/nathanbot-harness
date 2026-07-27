"""Shared operator contract — ONE source of truth for both the chat server
(server/server.py) and the voice daemon (scripts/voice/jarvis.py): the prompt AND
the tool scope, so the two channels cannot drift apart. The prompt template lives
in prompts/operator.md."""
import os
import sys
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


# ── operator tool scope — SHARED by the chat server and the voice daemon ──────
# Both channels reach the same operator with the same fuses, so they must have the
# same tool scope. They did not: server.py enumerated the nb verbs and derived a
# ~50-root credential denylist from nb_guard, while jarvis.py kept a
# `Bash(<nb>:*)` wildcard and denied only ~/.secrets — no second layer over
# browser cookies, keychains, Messages or its own rails, on the LESS supervised of
# the two channels. Constructed here so that cannot drift again.

OPERATOR_NB_VERBS = [
    # capture + read-only status
    "add", "inbox", "next", "status", "brief", "watch", "audit",
    # knowledge in / out — the whole point of the operator
    "remember", "feedback", "wiki", "study", "news", "activity", "usage", "recall",
    # planning + task hygiene (non-destructive forms)
    "triage", "plan", "done", "decide",
    # calendar staging — gcalendar.py is separately fused, so this can only stage
    # a [[CAL_BLOCK]] marker for the owner to approve
    "cal",
]
# NOT granted, deliberately: "perms". allowedTools matches by prefix, so
# Bash(nb perms:*) would also grant `nb perms set email.send always`. There is no
# way to split show from set at the flag level, so the whole verb stays out. The
# operator does not need to introspect its permissions; it needs to obey them.


def operator_allowed_tools(root):
    nb = os.path.join(root, "bin", "nb")
    return ["Read", "Grep", "Glob", "Edit", "Write", "WebSearch", "WebFetch",
            # BOTH names. The delegation tool was renamed Task -> Agent in CLI
            # 2.1.220; "Task" still resolves through an alias table today, so
            # granting both survives the alias being dropped OR restored.
            "Agent", "Task",
            *[f"Bash({nb} {v}:*)" for v in OPERATOR_NB_VERBS],
            f"Bash(python3 {root}/scripts/google/gmail.py:*)",
            f"Bash(python3 {root}/scripts/google/gcalendar.py:*)",
            # Read-only git, for the code-reviewer specialist. It declares Bash and
            # needs a diff to review; without this it spawns, reads nothing, and
            # reports that the code looks clean. None of these four can mutate a
            # repo, and guard-bash.py separately blocks `git push` when unattended.
            "Bash(git diff:*)", "Bash(git log:*)",
            "Bash(git show:*)", "Bash(git status:*)"]


def operator_add_dirs(root):
    """Extra directories the operator may reach, beyond its cwd.

    The career specialist reads and writes the resume master, which lives outside
    the repo. Without this it is hard-blocked — the transcripts show five turns of
    the owner asking it to check his folders and it correctly reporting that it
    cannot. Scoped to the one directory, never ~/Documents. Non-existent paths are
    dropped so a fresh checkout does not fail.
    """
    cands = [os.path.expanduser("~/Documents/Career/resumes")]
    return [d for d in cands if os.path.isdir(d)]


def operator_denied_tools(root):
    """Second layer behind the PreToolUse guard, derived from the guard's own list.

    Derived rather than restated: a hand-maintained copy drifts, and this file
    ships in the public template — hardcoding a machine's vault directory names
    would publish the layout that claude-hooks/deny-local.txt exists to keep
    private. nb_guard loads deny-local.txt itself, so per-machine additions flow
    through without appearing here.
    """
    h = os.path.expanduser("~")
    try:
        sys.path.insert(0, os.path.join(root, "claude-hooks"))
        from nb_guard import DENY_ALL as roots
    except Exception as e:
        # Loud. This silently returned the short list once already (a missing
        # `import sys` raised NameError straight into this handler), and a
        # quietly-weaker denylist is the exact failure this whole layer is for.
        print(f"WARNING: nb_guard unavailable ({e!r}) — falling back to a MINIMAL "
              f"credential denylist. The PreToolUse guard is still the real "
              f"boundary, but fix this.", file=sys.stderr)
        roots = [f"{h}/.secrets", f"{h}/.ssh", f"{h}/.aws", f"{h}/.gnupg",
                 f"{h}/.config/gh", f"{h}/Library/Keychains", f"{h}/Library/Cookies"]
    out = [f"{tool}({r}/**)" for r in roots
           for tool in ("Read", "Grep", "Glob", "Edit", "Write")]
    # not delegation — it appends to the task list. Denying it turns a wrong-tool
    # grab into a visible failure instead of a silent no-op.
    out.append("TaskCreate")
    for p in (f"{h}/.claude/settings.json", f"{h}/.claude/hooks",
              f"{root}/claude-hooks", f"{root}/config/permissions.json",
              f"{root}/config/accounts.json", f"{root}/prompts"):
        out += [f"Edit({p}/**)", f"Write({p}/**)", f"Edit({p})", f"Write({p})"]
    return out
