# nb — how the system works

One namespace. `nb <command>`. Improve the commands over time; the name never changes.

> **Command list:** `nb help` is the single authoritative surface (generated from
> `bin/nb`'s header). This doc explains the CONCEPTS only — don't list commands here,
> they drift.

## The loop
```
CAPTURE  →  TRIAGE  →  VERIFY
nb add      nb triage   nb audit
            nb plan     (self-heal)
```
Three steps, not four. There used to be an EXECUTE column (`nb run`); it was retired
2026-07-26 — see "Doing the work" below.

## Capture (never blocks you)
- `nb add "idea"` — terminal, fastest
- edit `tasks/inbox.md` directly — zero syntax, dump lines
- ask any harness to run `nb add` for you — mid-conversation

Capture never asks questions. Triage does the sorting later.

## Triage
`nb triage` reads the inbox, reads `shared-memory/OVERVIEW.md` + `config/projects.json`,
and files each idea as a task in `tasks/open/` with domain, project, priority, and status.
Vague items become `needs-decision` instead of guesses.

## Seeing what's next
- `nb next` — top ready tasks by priority
- `nb status` — ready / proposed / blocked / needs-decision / looks-done, plus what's waiting on YOU
- `nb decide` — resolve both kinds of thing waiting on you: questions, and tasks the weekly
  self-improvement pass believes are already finished (`looks-done`). It can flag a finish with
  evidence; only you can close one.

## Planning big things
`nb plan "launch the venue onboarding flow"` decomposes a goal into independent tasks.

## Doing the work
There is no execution command. Open the task file and work it in a Claude Code session,
against that one project.

`nb run` — a parallel executor that gave each task its own `claude -p` process — was retired
2026-07-26. It never successfully executed a single task: no task ever reached status `ready`
while it existed. Rationale and the recovery path (`git show 8e2243e:bin/nb`) are in
`tasks/done/t-0031-restart-or-retire-task-queue.md`. Capture still earns its keep:
`nb add` → `nb review` → `nb decide`.

## Autonomy (the safety model)
Set per project in `config/projects.json`:
- `auto-merge`      — implement, verify, merge. For low-risk/own projects.
- `auto-pr`         — implement, open PR, human merges. Default.
- `review-required` — implement, then STOP. Never pushes. **Client work uses this.**

> **Unresolved (2026-07-27):** the engine that read these was `nb run`, and it is gone. Whether
> anything still consumes these levels is an open question with its own task — do not assume
> from this section that a level is being enforced today.

## External sources
`config/projects.json` → `ingest` block. Jira, Google Drive, GitHub Issues can be enabled
to pull items in as tasks. All disabled by default; most work is solo.

## Self-healing
`nb audit` walks every self-check in `scripts/audit.sh` and finishes with a staleness pass
(`nb stale`) that asks whether memory's *claims* still hold. Run monthly.

The section list used to be transcribed here and said "11 sections" while the script had more —
the exact drift this doc warns about at the top. `scripts/audit.sh` is the list; read it there.
