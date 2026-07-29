#!/usr/bin/env bash
# selfapply.sh — shared guardrails for nathanbot's self-modifying passes
# (evolve, learn --apply). Source this, then:
#
#   sa_begin <pass> [wait-s]          # take the lock, snapshot what was ALREADY dirty
#     ... run the AI pass ...
#   sa_commit '<allow-regex>' "<msg>" # keep allowlisted NEW changes, revert the rest
#   sa_release                        # drop the lock
#
# Properties:
# - Only ONE self-modifying pass runs at a time (see "mutual exclusion" below).
# - No clean-tree requirement: the owner's pre-existing edits are never touched, never
#   committed, never reverted. Only files the PASS newly changed are considered.
# - Violations (new changes outside the allowlist) are reverted file-by-file.
# - Staged content is scanned for secret-looking strings before committing; any hit
#   reverts the whole pass (blocks the exfil-to-wiki path).
# - Commits are LOCAL only. Never pushes.
# - Every pass reports how many of its edits SURVIVED, not just how many it tried.

# ── mutual exclusion ─────────────────────────────────────────────────────────
# Each pass reverts every working-tree change outside its OWN allowlist. Run them
# concurrently and each pass's edits are the other's violations. Evolve's list is
# '^(wiki/|tasks/open/)'; learn's is the two model-of-the owner pages. On 2026-07-27
# learn reverted evolve's wiki/log.md edit one minute after it was written, and
# BOTH passes exited 0 -- the self-improvement loop had a success rate of zero
# while reporting success.
#
# They are scheduled 30 min apart, which would be enough. But rundue.sh catch-up
# fires missed jobs back-to-back with no gap, so every Monday the Mac is asleep at
# 08:00 the collision is guaranteed rather than unlucky. That is the common case.
#
# tasks/state/ is gitignored, so the lock is invisible to sa_commit's own
# `git status --porcelain -uall` scan (status omits ignored paths). That is why
# the lock lives there and not anywhere else under tasks/.
SA_LOCK="${NB_SA_LOCK:-$R/tasks/state/selfmod.lock}"
SA_EX_LOCKED=75                             # EX_TEMPFAIL
SA_WEDGED_S="${NB_SA_WEDGED_S:-3600}"       # a live pass held this long is hung
SA_PASS=""; SA_HELD=0; SA_PRE=""
SA_ATTEMPTED=0; SA_STANDING=0; SA_REVERTED=0

_sa_break_stale() {   # 0 = we cleared a dead/wedged lock, 1 = it is genuinely live
  local now pid started age m
  now=$(date +%s)
  if [ ! -s "$SA_LOCK/owner" ]; then
    # mkdir won the race microseconds ago and the owner line lands next.
    # Grace, not steal -- otherwise two passes can both "win".
    m=$(stat -f %m "$SA_LOCK" 2>/dev/null || echo 0)
    [ $(( now - m )) -lt 10 ] && return 1
    rm -rf "$SA_LOCK"; return 0
  fi
  pid=$(sed -n 's/.*pid=\([0-9]*\).*/\1/p' "$SA_LOCK/owner" 2>/dev/null)
  started=$(sed -n 's/.*started=\([0-9]*\).*/\1/p' "$SA_LOCK/owner" 2>/dev/null)
  age=$(( now - ${started:-0} ))
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    printf '  cleared a stale self-mod lock (owner pid %s is gone)\n' "${pid:-?}" >&2
    rm -rf "$SA_LOCK"; return 0
  fi
  if [ "$age" -gt "$SA_WEDGED_S" ]; then
    printf '  breaking a self-mod lock held %ss by live pid %s -- assuming wedged\n' "$age" "$pid" >&2
    rm -rf "$SA_LOCK"; return 0
  fi
  return 1
}

# sa_begin <pass-name> [wait-seconds]
#   0 = lock held, SA_PRE snapshotted, caller proceeds
#   1 = STAND DOWN. The caller must say so and exit $SA_EX_LOCKED -- never 0.
#       A pass that does nothing and exits clean is the bug, not the fix.
sa_begin() {
  SA_PASS="${1:-selfmod}"
  local wait="${2:-${NB_SA_WAIT:-0}}" waited=0 who
  mkdir -p "$(dirname "$SA_LOCK")" 2>/dev/null
  while :; do
    mkdir "$SA_LOCK" 2>/dev/null && break     # mkdir is atomic -- one pass at a time
    _sa_break_stale && { mkdir "$SA_LOCK" 2>/dev/null && break; }
    if [ "$waited" -ge "$wait" ]; then
      who="$(cat "$SA_LOCK/owner" 2>/dev/null || echo 'another pass')"
      printf '  SKIPPED: %s did not run.\n' "$SA_PASS" >&2
      printf '  The other self-improvement pass is still going (%s).\n' "$who" >&2
      printf '  Two at once delete each other'"'"'s edits, so this one stood down.\n' >&2
      printf '  Nothing was lost and nothing is broken. Re-run it yourself with: nb %s\n' "$SA_PASS" >&2
      return 1
    fi
    sleep 10; waited=$((waited+10))
  done
  SA_HELD=1
  printf '%s pid=%s started=%s\n' "$SA_PASS" "$$" "$(date +%s)" > "$SA_LOCK/owner"
  [ "$waited" -gt 0 ] && printf '  waited %ss for the other pass to finish\n' "$waited" >&2
  # -uall: list untracked FILES individually (default collapses new dirs to "dir/",
  # which would dodge the per-file allowlist match)
  SA_PRE="$(git -C "$R" status --porcelain -uall | sed 's/^...//')"
  return 0
}

sa_release() {   # idempotent; safe from any trap, at any point
  [ "${SA_HELD:-0}" = 1 ] || return 0
  SA_HELD=0
  rm -rf "$SA_LOCK" 2>/dev/null || true
}

# The line t-0035 asked for, printed by BOTH passes on EVERY exit path.
# The "Edits attempted: 1. Edits standing: 0" in tasks/logs/evolve.log was the
# model's own prose inside the run, captured by a `| tail -20`. It is not
# reproducible and it is not a check. This is.
sa_report() {
  printf '  %s -- Edits attempted: %d. Edits standing: %d.' \
    "$SA_PASS" "$SA_ATTEMPTED" "$SA_STANDING"
  [ "$SA_REVERTED" -gt 0 ] && \
    printf '  (%d reverted: outside this pass'"'"'s allowlist)' "$SA_REVERTED"
  printf '\n'
}

# sa_commit <allow-regex> <msg>
#   0  committed; SA_STANDING files landed
#   1  nothing this pass touched was allowlisted (benign)
#   2  secret scan tripped -- EVERYTHING reverted (loud)
#   3  the commit itself failed -- edits stranded in the tree (loud)
sa_commit() {
  local allow="$1" msg="$2" f keep=() viol=()
  SA_ATTEMPTED=0; SA_STANDING=0; SA_REVERTED=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    _sa_was_dirty "$f" && continue          # pre-existing — leave exactly as found
    if printf '%s' "$f" | grep -qE "$allow"; then keep+=("$f"); else viol+=("$f"); fi
  done < <(git -C "$R" status --porcelain -uall | sed 's/^...//')

  SA_ATTEMPTED=$(( ${#keep[@]} + ${#viol[@]} ))
  SA_REVERTED=${#viol[@]}

  if [ ${#viol[@]} -gt 0 ]; then
    printf '  reverting off-limits change(s): %s\n' "${viol[*]}" >&2
    for f in "${viol[@]}"; do
      git -C "$R" checkout -q -- "$f" 2>/dev/null || rm -f "$R/$f"
    done
  fi
  [ ${#keep[@]} -eq 0 ] && { sa_report; echo "  no allowlisted changes this pass"; return 1; }

  # secret scan: never let a pass commit anything key-shaped into the brain
  local staged_diff
  ( cd "$R" && git add -- "${keep[@]}" 2>/dev/null )
  staged_diff="$(git -C "$R" diff --cached -- "${keep[@]}" 2>/dev/null)"
  if printf '%s' "$staged_diff" | grep -qE 'AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|xoxb-|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|api[_-]?key["'"'"' ]*[:=]["'"'"' ]*[A-Za-z0-9_\-]{16,}'; then
    git -C "$R" reset -q -- "${keep[@]}"
    for f in "${keep[@]}"; do git -C "$R" checkout -q -- "$f" 2>/dev/null || rm -f "$R/$f"; done
    SA_REVERTED=$SA_ATTEMPTED
    printf '  ✗ secret-looking content in the pass — reverting everything\n' >&2
    sa_report
    return 2
  fi
  if git -C "$R" commit -q -m "$msg" -- "${keep[@]}" 2>/dev/null; then
    # Count what the COMMIT actually contains, not what we asked it to contain.
    # The whole point of t-0035 is that the self-report lied; a number derived
    # from intent rather than from the result would lie in exactly the same way.
    SA_STANDING=$(git -C "$R" diff-tree --no-commit-id --name-only -r HEAD | grep -c . || true)
    sa_report
    printf '  ✓ committed %d file(s) (local only — undo: git revert HEAD)\n' "$SA_STANDING"
    return 0
  fi
  sa_report
  printf '  ✗ %s: commit FAILED — %d edit(s) left uncommitted in the working tree\n' \
    "$SA_PASS" "${#keep[@]}" >&2
  return 3
}

_sa_was_dirty() {  # was this path dirty before the pass? (the owner's — hands off)
  printf '%s\n' "$SA_PRE" | grep -qxF "$1"
}
