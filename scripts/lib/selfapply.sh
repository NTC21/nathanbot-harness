#!/usr/bin/env bash
# selfapply.sh — shared guardrails for nathanbot's self-modifying passes
# (evolve --apply, learn --apply). Source this, then:
#
#   sa_begin                          # snapshot what was ALREADY dirty (the owner's work)
#   ... run the AI pass ...
#   sa_commit '<allow-regex>' "<msg>" # keep allowlisted NEW changes, revert the rest
#
# Properties:
# - No clean-tree requirement: the owner's pre-existing edits are never touched, never
#   committed, never reverted. Only files the PASS newly changed are considered.
# - Violations (new changes outside the allowlist) are reverted file-by-file.
# - Staged content is scanned for secret-looking strings before committing; any hit
#   reverts the whole pass (blocks the exfil-to-wiki path).
# - Commits are LOCAL only. Never pushes.

SA_PRE=""

sa_begin() {
  # -uall: list untracked FILES individually (default collapses new dirs to "dir/",
  # which would dodge the per-file allowlist match)
  SA_PRE="$(git -C "$R" status --porcelain -uall | sed 's/^...//')"
}

_sa_was_dirty() {  # was this path dirty before the pass? (the owner's — hands off)
  printf '%s\n' "$SA_PRE" | grep -qxF "$1"
}

sa_commit() {
  local allow="$1" msg="$2" f keep=() viol=()
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    _sa_was_dirty "$f" && continue          # pre-existing — leave exactly as found
    if printf '%s' "$f" | grep -qE "$allow"; then keep+=("$f"); else viol+=("$f"); fi
  done < <(git -C "$R" status --porcelain -uall | sed 's/^...//')

  if [ ${#viol[@]} -gt 0 ]; then
    printf '  reverting off-limits change(s): %s\n' "${viol[*]}" >&2
    for f in "${viol[@]}"; do
      git -C "$R" checkout -q -- "$f" 2>/dev/null || rm -f "$R/$f"
    done
  fi
  [ ${#keep[@]} -eq 0 ] && { echo "  no allowlisted changes this pass"; return 1; }

  # secret scan: never let a pass commit anything key-shaped into the brain
  local staged_diff
  ( cd "$R" && git add -- "${keep[@]}" 2>/dev/null )
  staged_diff="$(git -C "$R" diff --cached -- "${keep[@]}" 2>/dev/null)"
  if printf '%s' "$staged_diff" | grep -qE 'AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|xoxb-|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|api[_-]?key["'"'"' ]*[:=]["'"'"' ]*[A-Za-z0-9_\-]{16,}'; then
    printf '  ✗ secret-looking content in the pass — reverting everything\n' >&2
    git -C "$R" reset -q -- "${keep[@]}"
    for f in "${keep[@]}"; do git -C "$R" checkout -q -- "$f" 2>/dev/null || rm -f "$R/$f"; done
    return 2
  fi
  git -C "$R" commit -q -m "$msg" -- "${keep[@]}" 2>/dev/null && \
    printf '  ✓ committed %d file(s) (local only — undo: git revert HEAD)\n' "${#keep[@]}"
}
