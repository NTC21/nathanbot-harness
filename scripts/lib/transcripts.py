#!/usr/bin/env python3
"""Read what the Claude CLI already records about every run.

nathanbot's own telemetry captures a command name, a duration and an exit code.
It cannot say what a run cost, which model answered, which tools were used, or
whether a scheduled job did anything at all — which is why the overnight jobs
were dead for five days without anyone noticing.

The CLI has been recording all of it the whole time. Every `claude -p` run
persists a full transcript to ~/.claude/projects/<escaped-cwd>/<session>.jsonl
with per-message token usage, the model, and every tool call. Subagent runs land
under <session>/subagents/ with an agentType in a sibling .meta.json. Roughly
475 MB across 24 project directories, read by nothing until now.

So this parses rather than instruments: no new capture, no hot-path risk, and it
works retroactively over history that already exists.

The escaped-cwd directory name is LOSSY — '/', '_' and '.' all collapse to '-',
so ~/Projects/bodyfat_scanner and .../bodyfat-scanner would produce the same
directory. Never reconstruct a path from it; glob for the session id instead.
"""
import glob
import json
import os
import re
import subprocess
from collections import Counter

PROJECTS = os.path.expanduser("~/.claude/projects")
# three levels: this file is <root>/scripts/lib/transcripts.py
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Prompt openers -> the job that generated them. Used only when a run has no
# NB_JOB label in tasks/.traces.jsonl (i.e. every run before tracing existed).
_JOB_SIGNATURES = [
    ("You are nathanbot analyzing ITSELF", "evolve"),
    ("You are nathanbot improving ITSELF", "evolve"),
    ("You are nathanbot building a better model of THE OWNER", "learn"),
    ("You are nathanbot updating its model of THE OWNER", "learn"),
    ("You are triaging", "triage"),
    ("You are nathanbot processing", "digest"),
    ("You are the owner's news scout", "news"),
    ("You are nathanbot studying", "study"),
    ("Research tools, systems", "scout"),
    ("Decompose this goal", "plan"),
    ("the owner wants to durably remember", "remember"),
    ("You are interviewing the owner", "discuss"),
    ("You are nathanbot dreaming", "dream"),
    ("You are nathanbot noticing a repeated workflow", "skills"),
    ("You are nathanbot refining a skill", "skills-refine"),
    ("You are nathanbot —", "operator"),
    ("You are nathanbot talking", "operator"),
]


def classify(first_user_text):
    for sig, job in _JOB_SIGNATURES:
        if sig in first_user_text:
            return job
    return "unknown"


# ── prices ───────────────────────────────────────────────────────────────────
def _cli_path():
    try:
        p = subprocess.run([os.path.join(ROOT, "bin", "claudew")],
                           env={**os.environ, "NB_CHECK": "1"},
                           capture_output=True, text=True, timeout=20).stdout.strip()
        return os.path.realpath(p) if p else ""
    except Exception:
        return ""


def _cli_version():
    try:
        return subprocess.run(["claude", "--version"], capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def price_table(cache=os.path.join(ROOT, "tasks", ".model-prices.json")):
    """Per-model $/million-token rates, extracted from the installed CLI.

    Not a hardcoded table: the CLI ships its own catalog and uses it to compute
    the cost it reports, so extracting from the binary means the rates track the
    CLI by construction instead of going stale in a file nobody revisits. Keyed
    on the version string, so a CLI upgrade re-extracts automatically.

    Returns {} when extraction fails. Callers MUST treat that as "cannot price"
    and say so — never as zero.
    """
    ver = _cli_version()
    try:
        c = json.load(open(cache))
        if c.get("version") == ver and c.get("models"):
            return c["models"]
    except Exception:
        pass

    real = _cli_path()
    if not real or not os.path.exists(real):
        return {}
    try:
        blob = subprocess.run(["strings", real], capture_output=True,
                              text=True, timeout=120).stdout
    except Exception:
        return {}

    tiers = {}
    for m in re.finditer(r"(tier_\d+_\d+|haiku_\d+):\{([^}]*)\}", blob):
        vals = dict(re.findall(r"(\w+):([\d.]+)", m.group(2)))
        if "input" in vals and "output" in vals:
            tiers[m.group(1)] = {k: float(v) for k, v in vals.items()}

    # Bounded non-greedy across the whole record: a model entry carries nested
    # objects (provider_ids, max_output_tokens) between its id and its pricing
    # key, so a [^}]* scan cannot reach it. Non-greedy takes the NEAREST pricing,
    # which is this model's own.
    # Index the catalog id AND every provider id in the same record. Transcripts
    # record the dated first-party id (claude-haiku-4-5-20251001) while the
    # catalog id is the alias (claude-haiku-4-5), so keying on the catalog id
    # alone left real models unpriced.
    models = {}
    for m in re.finditer(r'id:"(claude-[\w.-]+)"(.{0,3000}?)pricing:"(\w+)"', blob, re.S):
        tier = tiers.get(m.group(3))
        if not tier:
            continue
        models.setdefault(m.group(1), tier)
        for pid in re.findall(r'"(claude[\w.:@-]+)"', m.group(2)):
            models.setdefault(pid.split("/")[-1], tier)
    if not models:
        return {}

    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump({"version": ver, "models": models}, open(cache, "w"))
    except OSError:
        pass
    return models


# Not real models: CLI-internal placeholders that never cost anything, and the
# local Ollama model from the fallback removed 2026-07-25. Reporting these as
# "unpriced" would train you to ignore a warning that matters.
NON_BILLABLE = ("<synthetic>", "unknown", "qwen3", "llama", "mistral", "gemma")


def cost_of(model, u, prices):
    """Dollars for one message's usage. None when the model has no price —
    the caller surfaces that as `unpriced`, never as 0. 0.0 for non-billable."""
    if any(model.startswith(n) or model == n for n in NON_BILLABLE):
        return 0.0
    p = prices.get(model)
    if not p:
        return None
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0) or 0)
    w1 = cc.get("ephemeral_1h_input_tokens", 0)
    return (u.get("input_tokens", 0) * p["input"]
            + u.get("output_tokens", 0) * p["output"]
            + u.get("cache_read_input_tokens", 0) * p.get("cache_read", 0)
            + w5 * p.get("cache_write_5m", p["input"])
            + w1 * p.get("cache_write_1h", p["input"])) / 1_000_000


# ── parsing ──────────────────────────────────────────────────────────────────
def iter_transcripts(since_epoch=None):
    """Every transcript path, newest first, mtime-filtered."""
    for f in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        if since_epoch and mt < since_epoch:
            continue
        yield f, mt


def summarize(path):
    """One session -> a flat dict. Tolerates malformed lines per-record."""
    s = {"session": os.path.basename(path)[:-6], "path": path, "cwd": "",
         "branch": "", "first_ts": "", "last_ts": "", "first_user": "",
         "models": Counter(), "tools": Counter(), "usage": {},
         "files": [], "assistant_msgs": 0, "out_tokens": 0, "sidechain": False,
         "entrypoint": ""}
    for line in _lines(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("type")
        if d.get("cwd") and not s["cwd"]:
            s["cwd"] = d["cwd"]
            s["branch"] = d.get("gitBranch") or ""
        if d.get("entrypoint") and not s["entrypoint"]:
            s["entrypoint"] = d["entrypoint"]
        ts = d.get("timestamp")
        if ts:
            s["first_ts"] = s["first_ts"] or ts
            s["last_ts"] = ts
        if d.get("isSidechain"):
            s["sidechain"] = True
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        if t == "user" and not s["first_user"]:
            c = m.get("content")
            if isinstance(c, str):
                s["first_user"] = c[:400]
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "text":
                        s["first_user"] = (b.get("text") or "")[:400]
                        break
        if t != "assistant":
            continue
        s["assistant_msgs"] += 1
        model = m.get("model") or "unknown"
        s["models"][model] += 1
        u = m.get("usage") or {}
        if u:
            agg = s["usage"].setdefault(model, Counter())
            for k in ("input_tokens", "output_tokens",
                      "cache_read_input_tokens", "cache_creation_input_tokens"):
                agg[k] += u.get(k, 0) or 0
            cc = u.get("cache_creation") or {}
            agg["w5"] += cc.get("ephemeral_5m_input_tokens", 0) or 0
            agg["w1"] += cc.get("ephemeral_1h_input_tokens", 0) or 0
            s["out_tokens"] += u.get("output_tokens", 0) or 0
        for b in m.get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            name = b.get("name") or "?"
            s["tools"][name] += 1
            inp = b.get("input") or {}
            if name in ("Write", "Edit", "NotebookEdit"):
                fp = inp.get("file_path") or inp.get("notebook_path")
                if fp:
                    s["files"].append(fp)
    return s


def user_turns(path):
    """Every user-authored turn in one session, with enough metadata to tell
    the owner's typing apart from hook injections and tool results.

    summarize() keeps only first_user[:400]; recall.py indexes assistant turns
    only. the owner's own words are in neither, and that is where the durable
    facts are. Filters NOTHING — policy belongs to the caller (dream_eyes.py),
    so this file stays the single reader of the transcripts.

    origin.kind == "human" is the CLI's own marker and is exact, but it only
    appears from 2026-07 onward: measured 1697 human vs 16403 missing across
    the corpus. Callers must treat a missing origin as "unknown", never as
    "not human", or they lose most of the history.
    """
    sid = os.path.basename(path)[:-6]
    for line in _lines(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "user" or d.get("isMeta"):
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str):
            text = c
        elif isinstance(c, list):
            # tool_result blocks are the tool talking back, never the owner
            text = "\n".join(b.get("text") or "" for b in c
                             if isinstance(b, dict) and b.get("type") == "text")
        else:
            continue
        if not text.strip():
            continue
        o = d.get("origin")
        yield {"text": text,
               "ts": d.get("timestamp") or "",
               "origin": o.get("kind") if isinstance(o, dict) else None,
               "prompt_source": d.get("promptSource"),
               "entrypoint": d.get("entrypoint") or "",
               "cwd": d.get("cwd") or "",
               "session": sid}


def tool_calls(path):
    """Every assistant tool_use in one session as (name, input_dict).

    summarize() walks the same blocks but keeps only the name and the
    Write/Edit paths. skill_eyes.py needs the inputs themselves — the bash
    command text and the Skill tool's `skill` argument.
    """
    for line in _lines(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "assistant":
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield b.get("name") or "?", (b.get("input") or {})


def _lines(path):
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if line.strip():
                    yield line
    except OSError:
        return


def subagents(path):
    """Dispatches launched by this session: [(agentType, meta_path)]."""
    d = path[:-6]
    out = []
    for meta in glob.glob(os.path.join(d, "subagents", "agent-*.meta.json")):
        try:
            out.append((json.load(open(meta)).get("agentType", "?"), meta))
        except Exception:
            out.append(("?", meta))
    return out


def session_cost(s, prices):
    """(dollars, unpriced_models). dollars is None only if nothing was priceable."""
    total, unpriced, any_priced = 0.0, set(), False
    for model, agg in s["usage"].items():
        u = {"input_tokens": agg["input_tokens"],
             "output_tokens": agg["output_tokens"],
             "cache_read_input_tokens": agg["cache_read_input_tokens"],
             "cache_creation": {"ephemeral_5m_input_tokens": agg["w5"],
                                "ephemeral_1h_input_tokens": agg["w1"]},
             "cache_creation_input_tokens": agg["cache_creation_input_tokens"]}
        c = cost_of(model, u, prices)
        if c is None:
            unpriced.add(model)
        else:
            total += c
            any_priced = True
    return (total if any_priced else None), unpriced


def trace_labels(path=os.path.join(ROOT, "tasks", ".traces.jsonl")):
    """session id -> {job, rc, dur_s, killed} from claudew's trace file.

    Absent for every run predating tracing; those fall back to classify().
    A start line with no matching end means the process was SIGKILLed (the
    subprocess timeout) — the grandchild claude survives and finishes writing
    its transcript, so the cost is real and must still be reported.
    """
    out = {}
    for line in _lines(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        sid = d.get("session")
        if not sid:
            continue
        rec = out.setdefault(sid, {"job": d.get("job", "unknown"), "killed": True})
        if d.get("job"):
            rec["job"] = d["job"]
        if d.get("ev") == "end":
            rec.update(rc=d.get("rc"), dur_s=d.get("dur_s"), killed=False)
    return out
