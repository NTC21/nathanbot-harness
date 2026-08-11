# nathanbot — Repository Guidance

> Canonical entry doc. Harness-agnostic. Every harness (Claude Code, Codex, Cursor, and any
> future one) points here. Do not duplicate this content into harness-specific files.

This repo is the owner's shared workspace for every AI harness they use (Claude Code, the web/desktop app, Codex, and any future harness). It holds cross-workspace assistant memory, the wiki, and planning context. It is designed to sync across machines via git, so a future always-on box is a drop-in.

**Use the memory system before answering strategy, planning, content, business, coding, research, or ops questions.**

## Ask before producing (highest-value behavior)

Output quality is capped by input quality. A confident answer built on guesses is worse than
a question, because the owner can't see which parts were invented.

**Ask when:**
- The request has more than one reasonable interpretation.
- You are about to infer a preference, constraint, or requirement that was never stated.
- A decision would be expensive to reverse (architecture, schema, naming, anything published).
- You notice you're about to write "I'll assume..." — that sentence is the signal.

**Don't ask when:**
- The answer is discoverable from the repo, the code, or memory. Look first, always.
- There's an obvious default and the cost of being wrong is low. Pick it, say you picked it.
- You've already asked about this and it's recorded in memory.

**How to ask:**
- Batch questions. One round of four beats four rounds of one.
- Explain the tradeoff so the choice is informed, not a quiz.
- Recommend an option and say why. "I'd pick B because X" is more useful than a neutral menu.
- **Never use jargon or internal names in a question without defining them.** If the owner has to
  ask what a term means, the question failed.

**Say what you don't know.** When output rests on an assumption, name the assumption in the
output. "This assumes X — tell me if that's wrong" is always better than silent confidence.

## Permissions (enforced, not advisory)

`config/permissions.json` defines what may happen without asking. It is checked in code —
`nb mail read` refuses body access while `read_bodies` is `ask`. Default email posture:
subjects always readable · bodies require asking · drafting fine · **sending never without
explicit approval** · deleting never. View/change: `nb perms` / `nb perms set <path> <level>`.

## Identity — before ANY outbound action

The owner may have multiple email identities. Sending from the wrong one is unrecoverable.
**Read `config/accounts.json` before sending email, replying, or creating a calendar invite.**

`config/accounts.json` lists each identity, marks exactly one as the authorized default, and flags
the rest as not authorized until the owner explicitly enables them. Only send from an identity
whose entry is marked authorized. If a task needs an identity that isn't authorized, STOP and say
so — never substitute a different identity without asking.

State plainly before drafting: `Acting as: <email>. Sending to: <recipient>.`
`send` takes a draft id only — it cannot compose. Draft → owner reviews → send.
`--yes` must restate the account key. Reading is fine unprompted; sending is not. Approval is
required for **both** the message text and the sending identity, every time.

## Acting on the owner's intent (don't make them memorize commands)

The owner should never have to recall exact `nb` syntax. When they say something in plain English,
map it to the command and run it. Confirm the interpretation only if ambiguous.

| They say (any phrasing) | You run |
|---|---|
| "make/start/create a new project X", "new app called X", "scaffold X" | `nb project new X --type <infer: next\|expo\|python\|node>` |
| "add this project" / "register X" (existing folder) | `nb project add <path>` |
| "capture / note / remember to <thing>" | `nb add "<thing>"` |
| "what should I work on", "what's next" | `nb next` |
| "what's my status", "where am I" | `nb status` |
| "brief me", "catch me up" | `nb brief` |
| "plan <goal>", "break down <goal>" | `nb plan "<goal>"` |
| "sort my inbox", "file these" | `nb triage` |
| "what do you know about me / this" | read the relevant memory, answer |
| "learn from how I work" | `nb learn` |
| "clean up my machine" | `nb tidy` (report first) |
| "did we ever...", "find where I...", "what did I do about X" | `nb recall "<query>"` (FTS over transcripts + commits) |
| "consolidate what I said", "remember today" | `nb dream` (proposes wiki edits; `--dry` to preview) |
| "what should I automate", "I keep doing this manually" | `nb skills` (proposes only — never installs) |
| "read/ingest this article", "learn this page" | `nb study <url\|file>` |
| "give me video/content ideas" | `nb ideas` (`--save <n>` appends to the Idea Bank) |
| "what's on my plate right now", "anything urgent" | `nb watch` |
| "update the CRM", "who's overdue for follow-up" | `nb crm due\|show\|append\|touch` |
| "how's the job search", "who accepted but never got a message" | `nb apps due\|show` |
| "put this in a Google Doc/Sheet", "pull that doc down" | `nb drive push\|upload\|pull\|show\|list` (identity-checked) |

Type inference for new projects: mentions of mobile/app/expo → expo; web/site/landing/dashboard →
next; script/ML/data → python; else node. State the type you picked. Autonomy defaults to
auto-merge for personal projects; if it sounds client-facing, use review-required and say so.

After `nb project new`, the project is fully wired (git, capabilities, wiki page, first task).
Tell the owner what got created and that they can just `cd` in and start.

## Memory Routing (reads)

When the user asks for planning, strategy, business, content, coding, research, or ops work:

1. Read `shared-memory/OVERVIEW.md` for high-level operator context and rules. It is bounded
   (kept under ~2000 chars) and meant to be loaded every session.
2. Read the relevant workspace `MEMORY.md`:
   - `workspace-admin/MEMORY.md` — finances, receipts, travel, admin.
   - `workspace-coding/MEMORY.md` — your apps, sites, infra.
   - `workspace-creative/MEMORY.md` — content, socials, funnels, media.
   - `workspace-research/MEMORY.md` — market research, leads intel, competitor data.

   These four ship as starters. Add or rename workspaces to match your own domains — nothing
   hardcodes this list.
3. Read `wiki/index.md` to find durable background pages, then open only the specific pages needed. `wiki/storage-policy.md` is the routing contract.
4. For recent context, skim the latest dated files under the relevant `workspace-*/memory/` folder. The root `memory/` folder is a machine-local index — not for reading.

Do not dump all memory into context by default. Pull the minimum relevant files and cite what was used when helpful.

## Memory Write-back (writes)

How work done in one harness becomes visible to the others:

- Before ending a session that meaningfully changed strategy, content, code, or state: append 2–5 summary lines to `<workspace>/memory/YYYY-MM-DD.md` (create the file if it's the day's first entry). A "session" = one continuous task thread. Write the summary when work wraps up, not per edit.
- Promote durable, cross-workspace facts to the wiki (`wiki/pages/` + one line in `wiki/index.md`, entry in `wiki/log.md`) per the storage policy.
- Update the workspace `MEMORY.md` only for curated, long-lived facts; bump its `Last updated` header when you do.
- Commit and push by default so other machines stay in sync.

## Memory model at a glance

- `shared-memory/OVERVIEW.md` — bounded (~2k chars), always loaded. Who the owner is, active
  ventures, hard rules. The single file every session starts from.
- `wiki/` — the durable knowledge graph (Obsidian-readable). Long-lived, cross-workspace facts.
  `wiki/pages/owner.md` is the self-page describing the owner.
- `workspace-*/MEMORY.md` — per-domain curated facts, hand-maintained.
- `workspace-*/memory/YYYY-MM-DD.md` — dated session notes, append-only.

## Repo Map

- `shared-memory/` — operator overview + rules (read first).
- `workspace-*/` — per-domain memory (MEMORY.md = curated, memory/ = dated notes).
- `wiki/` — long-term knowledge graph (Obsidian-readable). Canonical shared memory. `pages/owner.md` is the self-page.
- `bin/nb` — the CLI (`nb add`, `nb next`, `nb brief`, `nb mail`, `nb project`, ...).
- `bin/claudew` — the wrapper every scheduled job calls the `claude` CLI through (logging, job tagging).
- `config/` — configuration; `*.example.json` templates ship in the repo, real `*.json` are gitignored.
  - `config/accounts.json` — email identities (read before any outbound action).
  - `config/projects.json` — per-project autonomy levels.
  - `config/permissions.json` — enforced permission posture.
  - `config/profiles.json` — which capability layers compose onto which project.
- `capabilities/` — the capability layers themselves (one YAML per practice/stack), composed into
  a project's `.claude/CAPABILITIES.md` by `nb profile sync`.
- `scripts/` — automation helpers. `scripts/lib/` is shared code, not entry points.
- `claude-hooks/` — PreToolUse guards. These are what make the system safe to run unattended;
  install them with `claude-hooks/install.sh`.
- `prompts/operator.md` — the operator prompt: how a harness routes an arbitrary request.
- `server/server.py` — the headless brain/API the Telegram bridge and CLI talk to.
- `tasks/` — the queue. `inbox.md` is raw capture, `open/` and `done/` are filed tasks,
  `logs/` (created on first run) holds each scheduled job's output.
- `docs/` — setup guides: `nb.md` (concepts; `nb help` is the authoritative command list),
  `telegram.md`, `google-direct-auth.md`.
- `skills/` — reference skills a harness can load on demand (stack docs, not personal workflow).
- `media/` — scratch dir for generated audio/images; gitignored contents.
- `.claude/agents/` — specialist subagent definitions for Claude harnesses.

## Machine portability

No hardcoded machine paths in tracked files. Machine specifics live in `.env` (untracked); every
script resolves its own root from `$0`/`BASH_SOURCE`, which is what actually makes the repo
portable. Secrets live in `~/.secrets/`, never in the repo. Root `memory/` index is machine-local
and gitignored. To add an always-on machine later: clone the repo, copy the example configs, set
its `.env`, run the harness.
