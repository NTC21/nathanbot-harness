# START HERE — first run

Fifteen minutes from clone to a talking assistant. macOS steps below; Windows users:
do the same inside WSL2 and see the Windows table in [README.md](README.md).

## 1. Make the brain yours

```bash
for f in config/*.example.json; do cp "$f" "${f%.example.json}.json"; done
```

Then edit, in order of importance:

1. **`shared-memory/OVERVIEW.md`** — who you are, what you're working on, your hard
   rules. Every AI call reads this first; quality here caps quality everywhere.
2. **`config/projects.json`** — your repos + how autonomous the task engine may be in
   each (`auto-merge` / `auto-pr` / `review-required`).
3. **`config/permissions.json`** — what the assistant may do without asking. Defaults
   are conservative; change levels later with `nb perms set <path> <always|ask|never>`.
4. **`config/accounts.json`** — your email/calendar identities. Only mark an account
   authorized once you've actually connected it (step 6).

## 2. The CLI

```bash
echo "export PATH=\"$PWD/bin:\$PATH\"" >> ~/.zshrc && source ~/.zshrc
nb add "my first captured thought"    # capture → auto-triaged into a task
nb next                               # what to work on
nb brief                              # the daily briefing, on demand
```

`nb help` is the full list. You never need most commands — capture and decide are the
two you'll actually use; everything else runs on the schedule.

## 3. Your phone is the interface (Telegram, two-way + voice)

```bash
python3 server/server.py &        # the headless brain/API on :7777 — stdlib, no npm, no build

# create a bot via @BotFather, then:
mkdir -p ~/.secrets/telegram && chmod 700 ~/.secrets/telegram
printf '%s' '<BOTFATHER_TOKEN>' > ~/.secrets/telegram/bot_token && chmod 600 ~/.secrets/telegram/bot_token
nb tg --whoami                # message your bot -> it prints your chat id to save
nb schedule install-telegram  # always-on two-way bridge
```

Now text your bot from anywhere — "what's ready", "add: call the accountant" — or send a
**voice note** and it replies with a spoken one. Email sends arrive as Approve/Cancel buttons.
Full walkthrough: `docs/telegram.md`. There's no dashboard to open — it comes to you.

## 4. Voice ($0, no account)

```bash
brew install pipx && pipx install edge-tts && pipx ensurepath
nb speak "Systems online."
```

Better voices, still optional:
- **Fish Audio** (best butler voice): sign up at fish.audio, put your API key in
  `~/.secrets/fishaudio/api_key` (`chmod 600`). Pick any library voice —
  the id in the voice page URL is your `NB_FISH_VOICE`.
- **Voicebox** (local, private): install the app, then `nb schedule install-voicebox`.

## 5. Make it ambient

```bash
nb schedule install     # 07:30 brief · 22:35 dream · watcher every 2h · weekly learning
nb schedule status
```

Remove everything just as easily: `nb schedule remove`.

## 6. Optional connections

- **Google mail/calendar** — `nb mail login <account-key>` walks the OAuth flow per
  account; reading is safe-by-default, sending always requires your explicit yes.
- **Telegram (recommended) / Discord / iMessage delivery** — Telegram is two-way (see
  section 3); Discord via a webhook URL in `~/.secrets/discord/webhook_url`, iMessage via
  `NB_IMESSAGE_TO`. The 07:30 brief + proactive nudges fan out to whatever's configured.
- **Hands-free "Jarvis" wake word** — needs a free Picovoice key in
  `~/.secrets/picovoice/access_key`, then `nb jarvis once` (grants mic) and
  `nb schedule install-jarvis`.

## Where things live

| Path | Meaning |
|---|---|
| `tasks/inbox.md` → `tasks/open/` → `tasks/done/` | capture → triaged task → archive |
| `wiki/` | long-term knowledge (open it as an Obsidian vault) |
| `workspace-*/` | per-domain memory the AI maintains |
| `tasks/logs/` | every scheduled job's output |
| `~/.secrets/` | all keys, outside the repo, mode 700 |

Something broken? `nb audit` self-checks the memory system; `nb jarvis status` checks
the voice stack.
