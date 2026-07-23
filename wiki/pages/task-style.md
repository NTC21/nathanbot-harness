---
title: Task Style
type: reference
status: active
updated: 2026-01-01
---

# Task Style

How every generated task is written, so the queue stays scannable and each task is actionable
on its own. `bin/nb` reads this when it turns a raw thought into a filed task.

## Current state
Starter conventions — tune them to taste:

- **Title = an action**, not a topic. "Evaluate X vs Y and recommend one," not "Decision: X or Y."
- **One outcome per task.** If it has two "done when" conditions, split it.
- **Say what's owed by you.** If a task can't move until you supply something, name that in the
  title or a short "What I need from you" line — otherwise assume it's fully buildable.
- **Plain language in the body**, jargon defined once. A task you can't act on in six months is
  a task you'll re-triage.
- **Done when** — every task ends with a concrete completion test.

## Fields
Tasks are markdown files in `tasks/open/` with frontmatter: `id`, `title`, `domain`, `project`,
`status` (`ready` | `blocked` | `waiting`), `priority`, `created`. Keep the body human-first;
put anything implementation-specific under a short `*Technical:*` line at the end.

## Links
[[owner]] · [[index]] · [[conventions]]
