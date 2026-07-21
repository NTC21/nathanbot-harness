# nb — how the system works

One namespace. `nb <command>`. Improve the commands over time; the name never changes.

## The loop
```
CAPTURE  →  TRIAGE  →  EXECUTE  →  VERIFY
nb add      nb triage   nb run      nb audit
            nb plan     (parallel,  (self-heal)
                        isolated)
```

## Capture (never blocks you)
- `nb add "idea"` — terminal, fastest
- edit `tasks/inbox.md` directly — zero syntax, dump lines
- `/add` in Claude Code — mid-conversation (see .claude/skills)

Capture never asks questions. Triage does the sorting later.

## Triage
`nb triage` reads the inbox, reads `shared-memory/OVERVIEW.md` + `config/projects.json`,
and files each idea as a task in `tasks/open/` with domain, project, priority, and status.
Vague items become `needs-decision` instead of guesses.

## Seeing what's next
- `nb next` — top ready tasks by priority
- `nb status` — ready / running / blocked / needs-decision, plus what's waiting on YOU

## Planning big things
`nb plan "launch the venue onboarding flow"` decomposes a goal into independent tasks.

## Execution
`nb run` executes ready tasks in parallel. Each task:
- gets its own `claude -p` process with a **fresh context** (this is why context never overflows)
- is pinned to ONE project — never crosses project boundaries
- obeys that project's autonomy level from `config/projects.json`

## Autonomy (the safety model)
Set per project in `config/projects.json`:
- `auto-merge`      — implement, verify, merge. For low-risk/own projects.
- `auto-pr`         — implement, open PR, human merges. Default.
- `review-required` — implement, then STOP. Never pushes. **Client work uses this.**

The engine reads this per task and cannot override it.

## External sources
`config/projects.json` → `ingest` block. Jira, Google Drive, GitHub Issues can be enabled
to pull items in as tasks. All disabled by default; most work is solo.

## Self-healing
`nb audit` checks 8 things: bounded-core budget, Hermes caps, entry-doc wiring, orphan wiki
pages, staleness, index coverage, write-back freshness, secret leakage. Run monthly.
