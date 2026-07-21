# Storage Policy — the routing contract

Decides *where a fact lives*. Read before writing memory.

## Where things go
| Kind of fact | Location |
|---|---|
| Recent, session-specific ("today I did X") | `workspace-*/memory/YYYY-MM-DD.md` (append) |
| Curated, long-lived, single-workspace | that workspace's `MEMORY.md` |
| Durable, cross-workspace truth (canonical) | `wiki/pages/<slug>.md` + line in `wiki/index.md` + entry in `wiki/log.md` |
| Operator-wide context / brand rules | `shared-memory/OVERVIEW.md` |
| Machine-local, generated index | root `memory/` (gitignored, never hand-read/write) |
| Secrets / credentials | `~/.secrets/` — NEVER in this repo |

## Promotion flow
1. Capture happens in a dated `workspace-*/memory/` note during a session.
2. If a fact proves durable + reused, promote it: create/append `wiki/pages/<slug>.md`, add its line to `wiki/index.md`, log it in `wiki/log.md`.
3. If it's a curated single-workspace fact, put it in that `MEMORY.md` and bump `Last updated`.

## Rules
- Don't duplicate: a fact lives in exactly one canonical place; other files link to it.
- Don't dump memory into context — pull the minimum relevant files.
- Commit + push after write-back so other machines sync.
