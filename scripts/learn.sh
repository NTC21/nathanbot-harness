#!/usr/bin/env bash
# learn.sh — build a better model of THE OWNER from how he actually behaves.
#
# Distinct from `nb evolve`:
#   evolve  → improves the SYSTEM (commands, wiring, bugs)
#   learn   → improves the model of THE OWNER (preferences, patterns, priorities)
#
#   nb learn            analyze behavior, PROPOSE memory updates
#   nb learn --apply    ALSO auto-apply the safe tier: edits to the model-of-the owner pages
#                       that trace to an EXPLICIT nb-feedback entry (guarded, local commit)
#   nb learn --show     just show the raw behavioral evidence, no AI
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
DEC="$R/tasks/.decisions.jsonl"
TEL="$R/tasks/.telemetry.jsonl"
CHAT="$R/tasks/.chat.json"
FB="$R/tasks/.feedback.jsonl"
B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; X=$'\033[0m'

evidence() {
python3 - "$DEC" "$TEL" "$CHAT" "$R" "$FB" <<'PY'
import json, sys, os, collections, pathlib
dec, tel, chat, R, fb = sys.argv[1:6]

def rows(p):
    if not os.path.exists(p): return []
    out=[]
    for line in open(p):
        line=line.strip()
        if line:
            try: out.append(json.loads(line))
            except Exception: pass
    return out

D, T, F = rows(dec), rows(tel), rows(fb)

# Explicit corrections are the strongest signal — surface them first.
print("EXPLICIT FEEDBACK  (%d — highest-priority signal)" % len(F))
if F:
    for r in F[-20:]:
        print(f"  [{r.get('source','?')}] {r.get('note','')}")
else:
    print("  (none yet — logged via `nb feedback` or auto-detected by dream)")
print()

print("DECISIONS  (%d recorded)" % len(D))
if D:
    by_action = collections.Counter(d.get("action") for d in D)
    print("  by action:", dict(by_action))
    for field in ("project", "domain", "priority"):
        tally = collections.defaultdict(collections.Counter)
        for d in D:
            tally[d.get(field)][d.get("action")] += 1
        print(f"  by {field}:")
        for k, c in sorted(tally.items(), key=lambda kv: -sum(kv[1].values())):
            tot = sum(c.values())
            print(f"    {str(k):<22} n={tot:<4} " +
                  " ".join(f"{a}={n}" for a, n in c.most_common()))
    ages=[d["age_days"] for d in D if isinstance(d.get("age_days"), int)]
    if ages: print(f"  decision latency: avg {sum(ages)/len(ages):.1f}d, max {max(ages)}d")
    print("  dropped titles (what he does NOT want):")
    for d in D:
        if d.get("action") == "drop": print(f"    - {d.get('title')}")
    print("  deferred titles (not now, not never):")
    for d in D:
        if d.get("action") == "defer": print(f"    - {d.get('title')}")
else:
    print("  (none yet — decisions are recorded when you approve/defer/drop)")

print()
print("COMMAND USE  (%d records)" % len(T))
if T:
    c = collections.Counter(t.get("cmd") for t in T)
    print("  used:", ", ".join(f"{k}={v}" for k, v in c.most_common()))
    # Read the real dispatch table instead of a hardcoded list. The literal set
    # here listed 18 verbs while bin/nb dispatches 59, so "NEVER used" was
    # computed against a universe missing watch, news, study, wiki, remember,
    # feedback, cal, learn, stale, sync, schedule, profile, perms and more —
    # i.e. the learn pass reasoned about usage from a stale map of itself.
    sys.path.insert(0, os.path.join(R, "scripts"))
    try:
        from stale import nb_verbs
        allcmds = nb_verbs(canonical_only=True)
    except Exception:
        allcmds = set()
    # aliases and internals are not things the owner "chooses" to use
    allcmds -= {"help", "_logdecision"}
    unused = sorted(allcmds - set(c))
    print("  NEVER used:", ", ".join(unused) or "none")

print()
inbox = pathlib.Path(R)/"tasks"/".inbox-archive.md"
if inbox.exists():
    lines=[l.strip()[6:].split("<!--")[0].strip() for l in inbox.read_text().splitlines() if l.startswith("- [ ]")]
    print("HOW HE PHRASES CAPTURES  (%d)" % len(lines))
    for l in lines[-25:]: print("   ", l)

if os.path.exists(chat):
    try:
        h=json.load(open(chat))
        print()
        print("CHAT  (%d turns)" % len(h))
        for m in h[-8:]:
            print(f"  {m['role']}: {m['text'][:150]}")
    except Exception: pass
PY
}

if [ "${1:-}" = "--show" ]; then
  printf "%sBehavioral evidence%s\n\n" "$B" "$X"
  evidence
  exit 0
fi

NB_CHECK=1 "$R/bin/claudew" >/dev/null 2>&1 || { echo "claude CLI not found" >&2; exit 1; }
EV="$(evidence)"

# ── safe-tier auto-apply: encode EXPLICIT feedback into the model-of-the owner pages ──
# Operator never triggers this (NB_OPERATOR guard); scheduled Monday run does.
if [ "${1:-}" = "--apply" ] && [ -z "${NB_OPERATOR:-}" ]; then
  . "$R/scripts/lib/selfapply.sh"
  # WAIT rather than skip. Evolve runs 08:00 and this 08:30, but rundue.sh
  # catch-up fires missed jobs back-to-back, so after a slept-through Monday
  # this starts ~1 min into a 5-minute evolve run. Waiting keeps the intended
  # ordering without inventing a priority protocol, and the pass still lands
  # this Monday instead of next. NB_SA_WAIT=0 to skip instead.
  if ! sa_begin learn "${NB_SA_WAIT:-900}"; then
    exit "$SA_EX_LOCKED"        # NOT 0 -- a pass that did nothing must not look clean
  fi
  trap 'sa_release' EXIT INT TERM
  printf "%sApplying explicit feedback to the model of the owner...%s\n" "$B" "$X"
  NB_JOB=learn-apply "$R/bin/claudew" -p "You are nathanbot updating its model of THE OWNER — apply ONLY what he explicitly said.

SOURCE OF TRUTH — his explicit corrections (tasks/.feedback.jsonl):
$(tail -40 "$FB" 2>/dev/null || echo '(none)')

YOU MAY EDIT ONLY:
- $R/wiki/pages/owner.md
- $R/shared-memory/OVERVIEW.md   (keep under ~2000 chars — trim elsewhere if needed)

For each feedback entry not already reflected: add/adjust a TERSE line encoding it.
No speculation, no pattern-derived claims — explicit statements only. If everything is
already reflected, change nothing. Print one line per edit." \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Edit" "Write" "Grep" 2>&1 | tail -10
  sa_commit '^(wiki/pages/owner\.md|shared-memory/OVERVIEW\.md)$' \
    "auto-learn: encode explicit feedback into the model of the owner

Applied by 'nb learn --apply' (feedback-traceable edits only). Not pushed."
  # `|| true` used to swallow every one of these. rc 1 is benign; 2 and 3 are not.
  case $? in
    2) printf "%slearn: pass REVERTED — secret-looking content in the edits%s\n" "$Y" "$X" >&2 ;;
    3) printf "%slearn: commit FAILED — edits stranded in the working tree%s\n" "$Y" "$X" >&2 ;;
  esac
  sa_release
fi

printf "%sLearning from your behavior...%s\n" "$B" "$X"

NB_JOB=learn "$R/bin/claudew" -p "You are nathanbot building a better model of THE OWNER — not improving your own code.
(That's \`nb evolve\`. This is different: learn about the PERSON.)

BEHAVIORAL EVIDENCE (what he actually did, not what he said):
$EV

CURRENT MODEL OF HIM — read these before proposing anything:
- $R/shared-memory/OVERVIEW.md
- $R/wiki/pages/owner.md
- $R/workspace-*/MEMORY.md
- $R/wiki/index.md

ANALYZE, grounded in the evidence above:
0. EXPLICIT FEEDBACK outranks everything. If he stated a correction, treat it as ground truth
   and propose the memory/behavior change that encodes it — don't re-derive it from patterns.
1. What does he consistently APPROVE vs DROP? Dropped items reveal what he doesn't value —
   that should change how triage prioritizes in future.
2. Which projects/domains get attention vs neglect? Does the stated priority in memory match
   the observed behavior? Contradictions are the most valuable finding.
3. How does he phrase captures? Terse? Detailed? Does he capture problems or solutions?
   This should shape how triage interprets him.
4. Which commands does he never use? Either badly designed, badly surfaced, or he doesn't
   need them — say which you think and why.
5. Decision latency — what sits unresolved longest? That's friction to remove.
6. Anything in current memory now CONTRADICTED by behavior? Stale memory is worse than none.

OUTPUT:
- If the evidence is thin (few decisions, little usage), SAY SO PLAINLY and propose little.
  Do not invent patterns from 3 data points. Under-claiming beats over-claiming here.
- Propose specific edits to $R/wiki/pages/owner.md and/or $R/shared-memory/OVERVIEW.md
  (bounded ~2000 chars — if it would overflow, move detail to the wiki and link).
- SHOW the exact proposed text. Do NOT write any file yet.
- End with a single question that would most improve the model of him.

Be terse. Cite the specific evidence behind each claim — 'you dropped 3 of 4 P5 tasks' beats
'you seem to dislike low-priority work.'" \
  --allowedTools "Read" "Grep" "Glob" 2>&1 | tail -60

printf "\n%sProposals only — nothing written.%s Approve edits in chat or run again after more usage.\n" "$D" "$X"
