#!/usr/bin/env bash
# audit.sh — check memory wiring and staleness across nathanbot.
# Run periodically (Duke runs the equivalent as a recurring "workspace audit").
# Read-only: reports, never edits.
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
cd "$R"
TODAY=$(date +%s)
warn=0

hdr() { printf "\n\033[1m%s\033[0m\n" "$1"; }
bad() { printf "  ⚠️  %s\n" "$1"; warn=$((warn+1)); }
ok()  { printf "  ✅ %s\n" "$1"; }

hdr "1. Bounded core"
n=$(wc -c < shared-memory/OVERVIEW.md)
if [ "$n" -gt 2600 ]; then bad "OVERVIEW.md is $n chars — over budget. Move detail to wiki/pages/."
else ok "OVERVIEW.md $n chars (within budget)"; fi

hdr "2. Hermes bridge caps"
u=$(wc -c < hermes/USER.md 2>/dev/null || echo 0)
m=$(wc -c < hermes/MEMORY.md 2>/dev/null || echo 0)
[ "$u" -gt 1375 ] && bad "hermes/USER.md $u chars > 1375 cap" || ok "hermes/USER.md $u chars"
[ "$m" -gt 2200 ] && bad "hermes/MEMORY.md $m chars > 2200 cap" || ok "hermes/MEMORY.md $m chars"

hdr "3. Entry-doc wiring (harness-agnostic)"
grep -q 'AGENTS.md' CLAUDE.md 2>/dev/null && ok "CLAUDE.md points to AGENTS.md" || bad "CLAUDE.md does not point to AGENTS.md"
grep -q 'AGENTS.md' .cursorrules 2>/dev/null && ok ".cursorrules points to AGENTS.md" || bad ".cursorrules missing/not pointing"
[ "$(wc -l < CLAUDE.md)" -lt 15 ] && ok "CLAUDE.md is thin (pointer, not duplicate)" || bad "CLAUDE.md is fat — content may be duplicating AGENTS.md"

hdr "4. Orphan wiki pages (no inbound or outbound links)"
for f in wiki/pages/*.md; do
  [ -e "$f" ] || continue
  b=$(basename "$f" .md)
  out=$(grep -c '\[\[' "$f" 2>/dev/null; true)   # grep -c prints 0 itself; '|| echo 0' double-emits "0\n0"
  in=$(grep -rl "\[\[$b\]\]" wiki/ --include='*.md' 2>/dev/null | grep -v "$f" | wc -l | tr -d ' ')
  [ "$out" -eq 0 ] && bad "$b has no outbound links"
  [ "$in" -eq 0 ] && bad "$b has no inbound links (invisible in graph)"
done
[ "$warn" -eq 0 ] && ok "all pages linked"

hdr "5. Stale wiki pages (updated: > 30 days)"
for f in wiki/pages/*.md; do
  [ -e "$f" ] || continue
  d=$(grep -m1 '^updated:' "$f" | awk '{print $2}')
  [ -z "$d" ] && { bad "$(basename "$f") missing 'updated:' frontmatter"; continue; }
  ts=$(date -j -f "%Y-%m-%d" "$d" +%s 2>/dev/null) || continue
  days=$(( (TODAY - ts) / 86400 ))
  # 30, not 90. Nine of nineteen pages had `updated:` behind their real last-edit
  # date, so at 90 this could not fire — a check with a threshold longer than the
  # drift it measures is decoration.
  [ "$days" -gt 30 ] && bad "$(basename "$f" .md) not updated in $days days"
done

hdr "6. Index coverage"
for f in wiki/pages/*.md; do
  [ -e "$f" ] || continue
  b=$(basename "$f" .md)
  grep -q "\[\[$b\]\]" wiki/index.md || bad "$b not listed in wiki/index.md"
done

hdr "7. Write-back freshness"
# Only notes carrying a '## auto' section — that is writeback's output. `nb dream`
# writes dated notes too, under '## dream', and without this filter a healthy dream
# would print a green tick over a writeback that has been dead for a week.
last=$(grep -l '^## auto' workspace*/memory/*.md 2>/dev/null | xargs -r ls -t 2>/dev/null | head -1)
if [ -z "$last" ]; then bad "no dated session notes yet — write-back not happening"
else
  d=$(basename "$last" .md)
  ts=$(date -j -f "%Y-%m-%d" "$d" +%s 2>/dev/null) && {
    days=$(( (TODAY - ts) / 86400 ))
    # 3, not 14. AGENTS.md requires a note per meaningful session; exactly ONE has
    # ever been written, and at 14 days this printed a green tick over that.
    [ "$days" -gt 3 ] && bad "last session note is $days days old ($last) — AGENTS.md wants one per session" || ok "last session note $days days old"
  }
fi

hdr "8. Global context wiring"
G="$HOME/.claude/CLAUDE.md"
if [ -f "$G" ]; then
  grep -q 'nathanbot' "$G" && ok "global CLAUDE.md points to nathanbot" || bad "global CLAUDE.md exists but does not reference nathanbot"
  gn=$(wc -c < "$G")
  [ "$gn" -gt 4000 ] && bad "global CLAUDE.md is $gn chars — loads every session, trim it" || ok "global CLAUDE.md $gn chars (loads every session)"
else
  bad "no ~/.claude/CLAUDE.md — sessions outside a project get no nathanbot context"
fi

hdr "9. Secret leakage"
if git ls-files 2>/dev/null | grep -qE '(^|/)\.env$|\.pem$|\.p8$|AuthKey_'; then
  bad "secret-looking files are TRACKED in this repo"
else ok "no tracked secrets"; fi

hdr "10. Telemetry integrity"
tf="tasks/.telemetry.jsonl"
if [ -f "$tf" ]; then
  broken=$(python3 -c "
import json
b=0
for l in open('$tf'):
    l=l.strip()
    if l:
        try: json.loads(l)
        except Exception: b+=1
print(b)" 2>/dev/null || echo '?')
  [ "$broken" = 0 ] && ok "usage log clean (all lines parse)" \
    || bad "$broken malformed line(s) in .telemetry.jsonl — evolve/learn read garbage"
else ok "no telemetry yet"; fi

hdr "11. Wiki hygiene"
vaults=$(find . -name .obsidian -not -path '*/node_modules/*' | wc -l | tr -d ' ')
[ "$vaults" = 1 ] && ok "one Obsidian vault (wiki/)" \
  || bad "$vaults Obsidian vaults on this tree — nested vaults split the graph; keep only wiki/"
# grep -c prints 0 AND exits 1 when there are no matches, so `|| echo '?'` used to
# emit both — "0\n?" — and the clean case rendered as a warning reading "⚠️ 0 ?".
wikiprobs=$(python3 scripts/wiki_index.py --lint 2>/dev/null | grep -c ':' || true)
[ "$wikiprobs" = 0 ] && ok "wiki clean (schema, links, index in sync)" \
  || bad "$wikiprobs wiki problem(s) — run 'nb wiki lint'"

hdr "12. Specialist agents"
# Every agent named in the operator's roster must EXIST, and no agent file may
# carry the <root> placeholder — nothing substitutes it (agent files don't go
# through build_operator_prompt), so it reached the model literally and any path
# built from it was wrong. Four of six files had it.
missing=0
for a in $(sed -n '/^YOUR SPECIALIST TEAM/,/^Routing rules:/p' prompts/operator.md \
           | sed -n 's/^- \([a-z-]*\) *—.*/\1/p'); do
  [ -f ".claude/agents/$a.md" ] || { bad "operator.md routes to '$a' but .claude/agents/$a.md is missing"; missing=1; }
done
ph=$(grep -rl '<root>' .claude/agents/ 2>/dev/null | tr '\n' ' ')
[ -n "$ph" ] && bad "unsubstituted <root> in: $ph"
[ "$missing" = 0 ] && [ -z "$ph" ] && ok "roster intact ($(ls .claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ') agents, no placeholders)"

hdr "13. Cost visibility"
# A model the price table cannot price would otherwise contribute $0 to every
# report — a number that looks like an answer. Extraction is keyed on the CLI
# version, so this fires on the first run after an upgrade that adds a model.
up=$(python3 scripts/usage.py --days 7 2>/dev/null | grep -c 'unpriced' || true)
[ "$up" = 0 ] && ok "every model in the last 7d is priceable" \
  || bad "unpriced model(s) in the last 7d — 'nb usage' is undercounting; see scripts/lib/transcripts.py"

hdr "14. Task id collisions"
# next_id() scanned open/ + done/ only, so an id became available again the moment
# groom archived its holder. Fixed forward by d518ed5 (archive/ is now scanned);
# this is the check that stops it drifting back. The decision journal is keyed on
# these ids and _find_open resolves by prefix, so a collision silently mis-keys
# both. Nothing looks broken while it happens -- hence a check.
dupes=$(python3 - <<'PY' 2>/dev/null || echo '?'
import glob, os, re, collections
# The collisions that predate the fix. Renumbering them would edit records of
# real past decisions and break .decisions.jsonl keys -- the owner's call,
# 2026-07-27: fix forward, leave history alone.
#
# EIGHT, not three. t-0033's write-up named only 0027/0028/0029 because those are
# the ones with a live file in open/; d518ed5's commit message had the real count.
# A NINTH duplicate means next_id regressed and must shout, which is the only
# reason this list is enumerated rather than "ignore anything already duplicated".
# Do not add to it to quieten a warning -- a new entry here is a bug being hidden.
KNOWN = {"0003", "0004", "0005", "0012", "0013", "0027", "0028", "0029"}
seen = collections.defaultdict(list)
for d in ("open", "done", "archive", ""):
    for f in glob.glob(os.path.join("tasks", d, "t-*.md")):
        m = re.match(r"t-(\d+)", os.path.basename(f))
        if m:
            seen[m.group(1)].append(f)
out = [f"t-{i} in {len(fs)} files: {', '.join(sorted(os.path.dirname(x) or 'tasks' for x in fs))}"
       for i, fs in sorted(seen.items()) if len(fs) > 1 and i not in KNOWN]
print("\n".join(out))
PY
)
if [ "$dupes" = '?' ]; then bad "task id check failed to run"
elif [ -z "$dupes" ]; then ok "no duplicate task ids (8 pre-d518ed5 collisions grandfathered)"
else
  # here-string, not a pipe: a piped `while` runs in a subshell and bad()'s
  # increment to $warn would be discarded, so the run would end "0 warning(s)".
  while IFS= read -r l; do
    [ -n "$l" ] && bad "duplicate task id -- next_id regressed: $l"
  done <<< "$dupes"
fi

hdr "15. Command failures (last 7d)"
# rc was written on every telemetry line since 2026-07-21 and read by nothing.
# A rising crash rate belongs in the place the owner already checks. Counts only
# crashed/unrunnable: `nb stale` exiting non-zero because it FOUND drift is a
# result, and counting ~22 of those would make this fire constantly and be
# ignored -- the exact failure mode section 10's comment already names.
crashes=$(python3 - <<'PY' 2>/dev/null || echo '?'
import sys, os, time
sys.path.insert(0, os.path.join("scripts", "lib"))
import telemetry as TEL
b, _ = TEL.tally(TEL.rows("tasks/.telemetry.jsonl", time.time() - 7 * 86400))
print(TEL.count(b, TEL.REAL_FAILURES))
PY
)
if [ "$crashes" = '?' ]; then bad "command-failure check failed to run"
elif [ "$crashes" = 0 ]; then ok "no command crashes in the last 7d"
else bad "$crashes command crash(es) in the last 7d — 'nb usage --failures'"; fi

hdr "16. Dream freshness"
stamp="$R/tasks/state/dream.last"
if [ ! -f "$stamp" ]; then
  bad "nb dream has never completed — no tasks/state/dream.last (is the job installed?)"
else
  d=$(cut -dT -f1 <"$stamp")
  ts=$(date -j -f "%Y-%m-%d" "$d" +%s 2>/dev/null) && {
    days=$(( (TODAY - ts) / 86400 ))
    [ "$days" -gt 3 ] && bad "last dream run was $days days old ($d) — nightly consolidation is not happening" \
                      || ok "dream ran $days day(s) ago"
  }
  # A pass that runs nightly and never produces anything is the failure mode
  # usage.py exists to expose: it looks identical to a healthy one from outside.
  produced=$(git -C "$R" log --oneline --since=14.days --grep='^dream:' 2>/dev/null | grep -c . || true)
  pending=$(grep -l '^source: dream$' "$R"/tasks/open/*.md 2>/dev/null | grep -c . || true)
  if [ "${produced:-0}" -eq 0 ] && [ "${pending:-0}" -eq 0 ]; then
    bad "dream has produced nothing in 14 days — check tasks/logs/dream.log"
  else
    ok "dream produced $produced commit(s) and $pending open proposal(s)"
  fi
fi

hdr "17. Generated-skill integrity"
sk_bad=0
for f in "$R"/skills/_proposed/*/SKILL.md "$R"/skills/_refine/*/SKILL.md; do
  [ -e "$f" ] || continue
  dir=$(basename "$(dirname "$f")")
  for k in name description generated-by generated evidence; do
    grep -q "^$k:" "$f" || { bad "skills/_*/$dir/SKILL.md missing '$k:'"; sk_bad=1; }
  done
  grep -q "^name: ${dir}\$" "$f" || { bad "skills/_*/$dir/SKILL.md: name: does not match its directory"; sk_bad=1; }
done
# The gap manual activation creates: step 2 done (moved into skills/), step 3
# forgotten (never listed in a capability layer). profile.sh only symlinks names
# a layer names, so the skill sits there loading nowhere and looking installed.
for f in "$R"/skills/*/SKILL.md; do
  [ -e "$f" ] || continue
  grep -q '^generated-by: nb skills$' "$f" || continue
  slug=$(basename "$(dirname "$f")")
  grep -qE "^[[:space:]]*-[[:space:]]*${slug}[[:space:]]*\$" "$R"/capabilities/*.yaml 2>/dev/null \
    || { bad "skill '$slug' was activated but no capability layer lists it — it is INERT"; sk_bad=1; }
done
[ "$sk_bad" -eq 0 ] && ok "generated skills well-formed and wired"

hdr "18. Skill proposals not rotting"
prop_old=0
for d in "$R"/skills/_proposed/*/ "$R"/skills/_refine/*/; do
  [ -d "$d" ] || continue
  slug=$(basename "$d")
  age=$(( (TODAY - $(stat -f %m "$d" 2>/dev/null || echo "$TODAY")) / 86400 ))
  if [ "$age" -gt 30 ]; then
    if grep -ql "^skill-slug: ${slug}\$" "$R"/tasks/open/*.md 2>/dev/null; then
      bad "skill proposal '$slug' is ${age}d old and still undecided — 'nb decide'"
    else
      bad "skill proposal '$slug' is ${age}d old with no open task — orphan, delete it or file one"
    fi
    prop_old=1
  fi
done
[ "$prop_old" -eq 0 ] && ok "no stale skill proposals"

hdr "Memory vs reality (staleness)"
# Structure checks above prove the wiring; this proves the CLAIMS still hold.
# Confidently-wrong memory is worse than missing memory — a later session acts on it.
staleout=$(python3 "$R/scripts/stale.py" --quiet 2>/dev/null)
if [ -z "$staleout" ]; then ok "no stale references — memory matches reality"
else
  n=$(printf '%s\n' "$staleout" | grep -cE '^\s{4}\S+:[0-9]+')
  bad "$n stale reference(s) — run 'nb stale' for detail"
fi

hdr "Scheduled jobs actually running"
# t-0037 asked for a failure line here. The trigger: on 2026-08-03 the Claude
# OAuth session expired and EVERY AI pass died for three days. launchd kept
# firing them, each exited non-zero, and nothing said why -- the audit reported
# clean the whole time. A green check that cannot go red is the bug this repo
# keeps finding in itself.
#
# rc_means is what separates a crash from a finding: `nb stale` exits non-zero
# BY DESIGN when it finds drift, so counting raw non-zero exits would invent a
# failure rate that is mostly noise (the Option B rot t-0037 warned about).
TEL="$R/tasks/.telemetry.jsonl"
if [ -f "$TEL" ]; then
  # Auth is a RECENCY question, not a count. The first version counted
  # `claude-auth-expired` over the whole file, so the three 2026-08-07 lines held
  # the check red for days after `claude login` fixed it -- a red that can never
  # go green, which is t-0037's bug inverted (it named a green that could never go
  # red). Both teach the reader to skip the line, which is how the 2026-08-03
  # outage went unnoticed for three days to begin with. A 7d window does not fix
  # it either: an expiry on Monday reads as broken until Sunday no matter how many
  # passes have succeeded since.
  #
  # What actually answers "is auth dead RIGHT NOW" is bin/claudew's own trace.
  # Every AI pass runs through claudew, which writes an `end` line per run and an
  # auth-expired line ONLY when the run failed on auth. So if claudew has ended a
  # run since the last auth-expired, the login works -- no count, no window.
  # The auth line is written after the trace `end` within a single run, so a
  # currently-broken login always has auth_ts >= end_ts and stays red.
  #
  # Untraced runs (a caller passing its own --session-id) can only make this red
  # while auth is fine, never green while it is broken, and the next scheduled
  # pass clears it. False red on a dead check beats false green on a live one.
  #
  # Crashes are NOT counted here. Section 15 already counts them, through
  # scripts/lib/telemetry.py, and that lib is the only place that knows a rc=141
  # SIGPIPE is `interrupted` and not a crash -- `nb next | head` produces those
  # constantly. A second hand-rolled rule in this section reported 31 against
  # section 15's 12 for the same week, and would drift again the next time the
  # classifier learns something.
  read -r authbad capn truncn <<<"$(python3 - <<'PY' 2>/dev/null || echo "0 0 0"
import json, os, sys, time
sys.path.insert(0, os.path.join("scripts", "lib"))
import telemetry as TEL
# TEL._epoch is private but deliberate: it is the one place that knows the
# timestamp format, and a second strptime here is exactly the drift that gave
# this section two different crash counts for the same week.

last_auth = 0.0
capped = truncated = 0
week = time.time() - 7 * 86400
for r in TEL.rows("tasks/.telemetry.jsonl"):
    cmd = r.get("cmd")
    when = TEL._epoch(r.get("ts", "")) or 0.0
    if cmd == "claude-auth-expired":
        last_auth = max(last_auth, when)
    elif cmd == "claude-capped" and when >= week:
        capped += 1
    elif cmd == "claude-truncated" and when >= week:
        truncated += 1

# The trace file rotates at 5MB into .traces.jsonl.old. Only the live file is
# read: a rotation means megabytes of newer runs exist, so anything the old file
# could contribute is already superseded.
last_run = 0.0
try:
    with open("tasks/.traces.jsonl", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except Exception:
                continue
            if t.get("ev") == "end":
                last_run = max(last_run, TEL._epoch(t.get("ts", "")) or 0.0)
except FileNotFoundError:
    pass

print(int(last_auth > 0 and last_auth >= last_run), capped, truncated)
PY
)"
  if [ "${authbad:-0}" -gt 0 ] 2>/dev/null; then
    bad "CLAUDE LOGIN EXPIRED — every AI pass (evolve, learn, skills, dream, ideas, news) is dead until you run: claude login"
  else
    ok "claude auth healthy (a pass has run since the last auth failure)"
  fi
  [ "${capn:-0}" -gt 0 ] 2>/dev/null && ok "$capn capped run(s) in the last 7d (temporary — these heal on their own)"
  # A capped run does nothing and says so. A TRUNCATED run does half of something
  # and exits 0, so the pass that owns it commits and reports success -- the only
  # one of the three failure shapes that can leave memory in a state nobody knows
  # is partial. Windowed like the rest: this must be able to go green again.
  if [ "${truncn:-0}" -gt 0 ] 2>/dev/null; then
    bad "$truncn AI pass(es) ended mid-response in the last 7d — those runs are half-done; check what they committed"
  fi
fi

printf "\n\033[1m%s warning(s)\033[0m\n" "$warn"
