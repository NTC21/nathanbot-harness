# nathanbot

A personal AI system — one shared brain across every AI harness, synced via git.

It's three things working together:
- **Markdown memory** — your context, knowledge, and state as plain git-synced files any agent or human can read.
- **`nb` CLI** (`bin/nb`) — capture tasks, get briefed, triage, run work, manage projects.
- **Local dashboard** (`ui/`) — a web view over memory, tasks, and system health.

Model- and harness-agnostic by design: nothing is tied to one assistant. Use it from Claude Code,
Codex, Cursor, the web app, or anything that can read files and run a shell.

**Start here:**
- [`START-HERE.md`](START-HERE.md) — first-run setup (configs, secrets, dashboard).
- [`AGENTS.md`](AGENTS.md) — the canonical contract for AI agents (memory routing, write-back rules, repo map, `nb` commands).

Harness-specific files (`CLAUDE.md`, `.cursorrules`, ...) are thin pointers to `AGENTS.md`; don't
duplicate contract content into them.

## Secrets

Secrets never live in the repo. Config templates ship as `config/*.example.json` with placeholder
values only; real values go in your own `config/*.json` (gitignored) and secret material lives in
`~/.secrets/` (mode `700`). See `.env.example` for the names your environment expects.

## Quick start

```bash
# 1. Clone
git clone <your-fork-url> nathanbot && cd nathanbot

# 2. Copy the example configs and fill in your details
for f in config/*.example.json; do cp "$f" "${f%.example.json}.json"; done

# 3. Put your PATH on nb (optional, lets you call `nb` from anywhere)
echo 'export PATH="$PWD/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc

# 4. Run the dashboard
cd ui && npm install && npm run dev
```

Then open `AGENTS.md` and point your AI harness at this repo.
