# nathanbot — a personal Jarvis you actually own

A local-first personal AI system: one shared brain (plain markdown, synced with git),
one CLI, a JARVIS-style dashboard, a British voice, and scheduled autonomy — built on
top of whatever coding agent you already use (Claude Code, Codex, Cursor, ...).

Tell it things in plain English. It files tasks, briefs you every morning out loud,
watches your calendar and repos in the background, learns from your corrections, and
keeps working on a local model when your AI subscription hits its usage cap.

```
you ──▶ chat / voice / menu bar / CLI
              │
              ▼
        the operator          headless agent call (claude -p via bin/claudew)
        ─ reads your memory   falls back to a local Ollama model when capped
        ─ acts with nb
              │
              ▼
   markdown brain (git)       tasks/ · wiki/ · workspaces/ · config/
              │
              ▼
   dashboard + voice          JARVIS HUD on localhost:7777 · speak.sh voice chain
```

## What it does day-to-day

- **07:30 brief** — spoken + notification: what's waiting on you, what's ready, today's
  first calendar event. Optionally delivered to Discord/iMessage.
- **Capture anywhere** — menu-bar click, global hotkey, `nb add "thought"`, or just tell
  the chat. AI triages everything into readable tasks; you never write frontmatter.
- **Ambient watcher** — every 30 min: imminent meetings (spoken warning), dirty repos,
  VIP email senders.
- **Nightly digest** — mines your daily notes + chat into tasks and durable wiki facts.
- **Weekly self-improvement** — `evolve` proposes system upgrades, `learn` updates its
  model of *you* from your explicit feedback, within hard guardrails (allowlisted paths,
  secret scans, local-only commits).
- **JARVIS HUD** — dark cyan dashboard (Dock app or browser): task queue, decisions
  waiting on you with approve/defer/drop, calendar, system health, live activity log,
  and a chat that talks back out loud. Click the orb (or press Esc) to hush it.

## Requirements

- **macOS** (Apple Silicon or Intel) — the full experience. See [Windows](#windows) below.
- A coding agent CLI on your PATH (built against **Claude Code**; anything with a
  `claude -p`-style headless mode can be swapped in via one wrapper).
- Python 3 (ships with macOS), Homebrew for the optional extras.

Nothing here needs a paid API key. Every voice and fallback tier has a free path.

## Quick start (macOS)

```bash
git clone https://github.com/NTC21/nathanbot-harness.git nathanbot && cd nathanbot

# 1. copy example configs and make them yours
for f in config/*.example.json; do cp "$f" "${f%.example.json}.json"; done
$EDITOR config/projects.json config/permissions.json shared-memory/OVERVIEW.md

# 2. put nb on your PATH
echo "export PATH=\"$PWD/bin:\$PATH\"" >> ~/.zshrc && source ~/.zshrc

# 3. dashboard (python stdlib — no npm, no build step)
python3 ui/server.py &          # then open http://127.0.0.1:7777
bash scripts/build-app.sh       # optional: native Dock app wrapper

# 4. make it ambient (launchd: brief, digest, watcher, weekly learning)
nb schedule install

# 5. voice (free, no account): British neural voice via Microsoft edge-tts
brew install pipx && pipx install edge-tts && pipx ensurepath
nb speak "Good evening. All systems online."

# 6. never run out of AI (optional, ~5GB): local fallback model
bash scripts/setup-fallback.sh install
```

Say hello: open the dashboard and type, or `nb brief --speak`.

## The pieces

| Piece | What it is |
|---|---|
| `bin/nb` | The CLI. `nb add`, `nb brief`, `nb next`, `nb decide`, `nb remember`, `nb watch`, ... `nb help` lists everything. |
| `bin/claudew` | Wrapper around your agent CLI. Detects "usage limit reached" and transparently retries the same call against a local Ollama model (`/v1/messages` on :11434). |
| `ui/` | `server.py` (stdlib HTTP + JSON API on :7777) and `web/index.html` (the HUD — one file, no build step). |
| `app/` | Tiny Swift WKWebView wrapper so the HUD lives in your Dock. |
| `scripts/speak.sh` | Voice chain: Fish Audio → edge-tts → Voicebox → ElevenLabs → OpenAI → `say`. First available backend wins; every reply is sanitized to sound human. |
| `scripts/schedule.sh` | Installs/removes all launchd jobs. |
| `prompts/operator.md` | The operator's system prompt — the personality and the rules. |
| `tasks/`, `wiki/`, `workspace-*/` | The markdown brain. Tasks with frontmatter, an Obsidian-compatible knowledge wiki, per-domain memory. |

## Customizing it (the point of the whole thing)

Everything is a text file. The system is designed to be reshaped:

- **Your identity & goals** — `shared-memory/OVERVIEW.md` (who you are, ventures, hard
  rules). Every AI call reads this first.
- **Personality** — `prompts/operator.md`. Want less butler, more drill sergeant? Edit it.
- **Voice** — env vars, no code: `NB_EDGE_VOICE` (any [edge-tts voice](https://github.com/rany2/edge-tts)),
  `NB_FISH_VOICE` (any fish.audio library voice id), `NB_VOICEBOX_PROFILE`, `NB_SPEAK_MAX`
  (spoken-length cap). Reorder/remove tiers by editing `scripts/speak.sh` top-down.
- **What it may do without asking** — `config/permissions.json` (email read/draft/send,
  calendar, git push, purchases...), enforced in code, adjustable with `nb perms set`.
- **Autonomy per project** — `config/projects.json`: `auto-merge`, `auto-pr`, or
  `review-required` per repo. The task engine cannot override it.
- **Schedules** — times live in one place, `scripts/schedule.sh`; rerun
  `nb schedule install` after editing.
- **Local fallback model** — `NB_OLLAMA_MODEL` (default picked by your RAM: qwen3:8b
  under 32GB, qwen3:14b above).
- **Different agent CLI** — point `NB_CLAUDE_BIN` at any binary with a compatible
  headless mode; `bin/claudew` is the only place the agent is invoked.
- **Task style** — `wiki/pages/task-style.md` controls how every generated task is
  written (the "never make me ask what is this" rule).

## Security model

- **Secrets never enter the repo.** Keys live in `~/.secrets/` (mode 700), read at call
  time, passed via stdin — never argv, never committed. Release/self-improvement passes
  run a secret-pattern scan and revert on any hit.
- **The operator is fused.** The chat/voice agent runs with `NB_OPERATOR=1`: it cannot
  send email, create calendar invites, push, merge, or trigger the task engine — those
  paths hard-refuse in code, not in the prompt. It's also denied all reads of `~/.secrets`.
- **Self-modification is sandboxed.** Weekly `evolve`/`learn` passes may only touch
  allowlisted paths, never your uncommitted work, and commit locally so `git revert` is
  always one command away.

## Windows

The brain is portable; the ambient layer is macOS-native today.

| Works on Windows (via **WSL**) | macOS-only today |
|---|---|
| `nb` CLI, tasks, wiki, triage, digest | menu-bar HUD (SwiftBar), Dock app |
| dashboard (`python3 ui/server.py`, open in any browser) | launchd schedules (use `cron` in WSL instead) |
| `claudew` + Ollama fallback ([Ollama runs on Windows](https://ollama.com)) | voice output chain (`afplay`/`say`; swap in any CLI player) |
| Google mail/calendar scripts | global hotkeys (skhd) |

Practical Windows setup: install WSL2 + Ubuntu, follow the Quick start inside WSL
(skip steps 3's Dock app, 4, and 5), run the dashboard and open it from Windows at
`http://127.0.0.1:7777`, and schedule `nb brief`/`nb digest` with cron. Contributions
that port the ambient layer are welcome.

## Philosophy

- **Plain files over databases** — everything greppable, diffable, yours.
- **One brain, many harnesses** — `AGENTS.md` is the contract; Claude Code, Codex,
  Cursor and friends all read the same memory.
- **Autonomy inside fuses** — the system acts on its own, but destructive and outward
  actions are code-gated, not vibes-gated.
- **$0 by default** — every capability has a free tier: local models, free neural TTS,
  no required API keys.

## License

MIT — see [LICENSE](LICENSE).
