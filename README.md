# nathanbot — a personal Jarvis you actually own

A local-first personal AI you **text and talk to from your phone**. One shared brain (plain
markdown, synced with git), one CLI, a British voice, and scheduled autonomy — built on top of
whatever coding agent you already use (Claude Code, Codex, Cursor, ...).

Text it in plain English or send a voice note. It files tasks, briefs you every morning, watches
your calendar and repos, pings you *before* meetings, learns from your corrections, and keeps
working on a local model when your AI subscription hits its usage cap.

```
📱 you  ── text / voice note (Telegram) · CLI · morning brief
              │
              ▼
   Telegram bridge ──────────  long-polls (survives laptop sleep, 24h queue)
              │  only answers YOUR chat id
              ▼
        the operator          headless agent call (claude -p via bin/claudew)
        ─ reads your memory   falls back to a local Ollama model when capped
        ─ acts with nb        outward actions are code-fused (approve to send)
              │
              ▼
   markdown brain (git)       tasks/ · wiki/ · workspaces/ · config/
              │
              ▼
   it reaches back  ──────────  replies (text + spoken voice note) · proactive nudges
```

There's no dashboard to open. The interface is your pocket — it comes to you.

## What it does day-to-day

- **Two-way on Telegram** — text your bot anything ("what's ready", "add: call the accountant",
  "draft an email to X"). It acts and replies. Send a **voice note** → it transcribes, thinks,
  and replies with a **spoken voice note** in a British voice. Hands-free, from anywhere.
- **Proactive reach-out** — it messages *you* first: a heads-up before calendar events, the
  morning brief, anything waiting on you. You don't check it; it checks in.
- **07:30 brief** — what's waiting, what's ready, today's first event — pushed to your phone
  (and spoken locally).
- **Time-blocking** — `nb plan-day` turns your top ready tasks into calendar blocks around your
  real events; approve to write them.
- **Capture anywhere** — `nb add "thought"`, a text, or a voice note. AI triages everything into
  readable tasks; you never write frontmatter.
- **Ambient watcher + nightly digest + weekly self-improvement** — imminent meetings, dirty
  repos, VIP email; mines your notes into tasks/wiki; `evolve`/`learn` improve the system within
  hard guardrails (allowlisted paths, secret scans, local-only commits).

## Requirements

- **macOS** (Apple Silicon or Intel) for the full ambient layer. The phone bridge + CLI are
  portable — see [Windows](#windows).
- A coding-agent CLI on your PATH (built against **Claude Code**; anything with a `claude -p`
  headless mode swaps in via one wrapper).
- Python 3 (ships with macOS), Homebrew for optional extras.

Nothing here needs a paid API key. Every voice and fallback tier has a free path.

## Quick start (macOS)

```bash
git clone https://github.com/NTC21/nathanbot-harness.git nathanbot && cd nathanbot

# 1. copy example configs and make them yours
for f in config/*.example.json; do cp "$f" "${f%.example.json}.json"; done
$EDITOR config/projects.json config/permissions.json shared-memory/OVERVIEW.md

# 2. put nb on your PATH
echo "export PATH=\"$PWD/bin:\$PATH\"" >> ~/.zshrc && source ~/.zshrc

# 3. the headless brain/API (python stdlib — no npm, no build step)
python3 ui/server.py &          # the CLI + phone bridge talk to this on :7777

# 4. your phone = the interface (Telegram, two-way + voice). See docs/telegram.md
#    - create a bot via @BotFather, save the token:
mkdir -p ~/.secrets/telegram && chmod 700 ~/.secrets/telegram
printf '%s' '<BOTFATHER_TOKEN>' > ~/.secrets/telegram/bot_token && chmod 600 ~/.secrets/telegram/bot_token
nb tg --whoami                  # message your bot -> it prints your chat id to save

# 5. make it ambient (launchd: brief, digest, watcher, phone bridge, proactive nudges)
nb schedule install
nb schedule install-telegram    # always-on two-way phone bridge
nb schedule install-nudge       # proactive calendar heads-ups

# 6. voice (free, no account): British neural voice via Microsoft edge-tts
brew install pipx && pipx install edge-tts && pipx ensurepath
nb speak "Good evening. All systems online."

# 7. never run out of AI (optional, ~5GB): local fallback model
bash scripts/setup-fallback.sh install
```

Say hello: text your bot, or `nb brief --speak`.

## The pieces

| Piece | What it is |
|---|---|
| `bin/nb` | The CLI. `nb add`, `nb brief`, `nb next`, `nb plan-day`, `nb decide`, `nb remember`, `nb tg`, ... `nb help` lists everything. |
| `bin/claudew` | Wrapper around your agent CLI. Detects "usage limit reached" and transparently retries the same call against a local Ollama model (`/v1/messages` on :11434). |
| `scripts/telegram/listen.py` | The two-way phone bridge — long-polls Telegram, routes your texts/voice notes to the operator, replies (text + spoken voice note). Only answers your chat id. |
| `scripts/proactive/nudge.py` | Pings you before calendar events. Runs every 10 min, dedups. |
| `ui/server.py` | The **headless brain/API** (stdlib HTTP + JSON on :7777). The CLI, the phone bridge, and voice all hit the same operator here. No dashboard — this is backend only. |
| `scripts/speak.sh` | Voice chain: Fish Audio → edge-tts → Voicebox → ElevenLabs → OpenAI → `say`. First available backend wins; every reply is sanitized to sound human. |
| `scripts/schedule.sh` | Installs/removes all launchd jobs (brief, digest, watcher, telegram, nudge, ...). |
| `prompts/operator.md` | The operator's system prompt — the personality and the rules. |
| `tasks/`, `wiki/`, `workspace-*/` | The markdown brain. Tasks with frontmatter, an Obsidian-compatible wiki, per-domain memory. |

## Customizing it (the point of the whole thing)

Everything is a text file, designed to be reshaped:

- **Your identity & goals** — `shared-memory/OVERVIEW.md` (who you are, ventures, hard rules).
  Every AI call reads this first.
- **Personality** — `prompts/operator.md`. Want less butler, more drill sergeant? Edit it.
- **Voice** — env vars, no code: `NB_EDGE_VOICE` (any [edge-tts voice](https://github.com/rany2/edge-tts)),
  `NB_FISH_VOICE`, `NB_VOICEBOX_PROFILE`, `NB_SPEAK_MAX`. Reorder tiers in `scripts/speak.sh`.
- **Proactive window** — `NB_NUDGE_MIN` (how many minutes before an event it pings you).
- **What it may do without asking** — `config/permissions.json` (email, calendar, git, ...),
  enforced in code, adjustable with `nb perms set`.
- **Autonomy per project** — `config/projects.json`: `auto-merge`, `auto-pr`, `review-required`.
- **Schedules** — `scripts/schedule.sh`; rerun `nb schedule install` after editing.
- **Local fallback model** — `NB_OLLAMA_MODEL` (RAM-based default: qwen3:8b under 32GB, else qwen3:14b).
- **Different agent CLI** — point `NB_CLAUDE_BIN` at any binary with a headless mode; `bin/claudew`
  is the only place the agent is invoked.
- **Task style** — `wiki/pages/task-style.md` controls how every generated task is written.

## Security model

- **Secrets never enter the repo.** Keys live in `~/.secrets/` (mode 700), read at call time,
  passed via stdin — never argv, never committed. Release/self-improvement passes secret-scan and
  revert on any hit.
- **The operator is fused.** The chat/voice agent runs with `NB_OPERATOR=1`: it cannot send email,
  create calendar invites, push, merge, or trigger the task engine — those paths hard-refuse in
  code, not in the prompt. It's also denied all reads of `~/.secrets`.
- **Sending email needs your tap.** The operator can only *stage* a send; you approve the real
  recipient with an **Approve** button in Telegram (or from a terminal) — an action the model
  itself cannot perform.
- **The phone bridge answers only you.** Messages from any chat id other than yours are ignored.
- **Self-modification is sandboxed.** Weekly `evolve`/`learn` may only touch allowlisted paths,
  never your uncommitted work, and commit locally so `git revert` is one command away.

## Windows

The brain, the CLI, and the **phone bridge** are portable; the ambient scheduling is macOS-native.

| Works on Windows (via **WSL**) | macOS-only today |
|---|---|
| `nb` CLI, tasks, wiki, triage, digest | launchd schedules (use `cron`/Task Scheduler in WSL) |
| **Telegram bridge + voice** (`nb tg`) — your phone works anywhere | local voice playback (`afplay`/`say`; swap any CLI player) |
| `claudew` + Ollama fallback ([Ollama on Windows](https://ollama.com)) | menu-bar + global hotkeys (SwiftBar/skhd) |
| Google mail/calendar scripts | |

Practical Windows setup: install WSL2 + Ubuntu, follow Quick start inside WSL (schedule
`nb brief`/`nb telegram`/`nb nudge` with cron instead of launchd). The Telegram interface is the
same everywhere — that's the point.

## Philosophy

- **Plain files over databases** — everything greppable, diffable, yours.
- **One brain, many harnesses** — `AGENTS.md` is the contract; Claude Code, Codex, Cursor read the same memory.
- **It comes to you** — a phone you text, not a dashboard you open. Autonomy means reaching out.
- **Autonomy inside fuses** — it acts on its own, but destructive and outward actions are code-gated.
- **$0 by default** — local models, free neural TTS, no required API keys.

## License

MIT — see [LICENSE](LICENSE).
