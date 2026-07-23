---
title: Conventions
type: reference
status: active
updated: 2026-01-01
---

# Conventions

The rules **every** harness (Claude Code, Codex, Cursor, …) obeys when working in this system.
This is where coding standards, behavioral rules, and cross-harness preferences live — the
operator writes here automatically when you give it durable feedback, so you should never have
to repeat yourself twice.

## Current state
Starter page. Add your own rules as terse bullets. Examples of the kind of thing that belongs here:

- Commit in small, logical steps during code changes — don't wait to be asked.
- Prefer editing an existing file over creating a new one.
- Show reasoning and tradeoffs, not just conclusions.
- Never introduce a term or internal name without defining it once.

## How it fills up
- The operator routes any rule/preference "every harness should obey" to this page (see
  `prompts/operator.md` and `bin/nb`).
- Keep each rule to one line. If a rule needs a paragraph, it probably belongs in its own
  wiki page that this one links to.

## Links
[[owner]] · [[index]] · [[task-style]]
