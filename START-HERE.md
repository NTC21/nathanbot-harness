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

## 3. Dashboard + Dock app

```bash
python3 ui/server.py &        # stdlib only — no npm, no build
open http://127.0.0.1:7777
bash scripts/build-app.sh     # optional: installs ~/Applications/nathanbot.app
```

Chat in the middle; your queue, decisions, calendar, system health, and activity log
around it. Click the orb or press Esc to stop it talking.

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
nb schedule install     # 07:30 brief · 22:00 digest · watcher every 30 min · weekly learning
nb schedule status
```

Remove everything just as easily: `nb schedule remove`.

## 6. Optional connections

- **Google mail/calendar** — `nb mail login <account-key>` walks the OAuth flow per
  account; reading is safe-by-default, sending always requires your explicit yes.
- **Discord/iMessage delivery** — webhook URL in `~/.secrets/discord/webhook_url`
  and/or `NB_IMESSAGE_TO`; the 07:30 brief fans out to them.
- **Hands-free "Jarvis" wake word** — needs a free Picovoice key in
  `~/.secrets/picovoice/access_key`, then `nb jarvis once` (grants mic) and
  `nb schedule install-jarvis`.
- **Never-run-out fallback** — `bash scripts/setup-fallback.sh install` (Ollama +
  a local model sized to your RAM). When your subscription caps, `bin/claudew`
  silently reroutes calls to it; the HUD shows "LOCAL BRAIN" while it's covering.

## Where things live

| Path | Meaning |
|---|---|
| `tasks/inbox.md` → `tasks/open/` → `tasks/done/` | capture → triaged task → archive |
| `wiki/` | long-term knowledge (open it as an Obsidian vault) |
| `workspace-*/` | per-domain memory the AI maintains |
| `tasks/logs/` | every scheduled job's output |
| `~/.secrets/` | all keys, outside the repo, mode 700 |

Something broken? `nb audit` self-checks the memory system; `nb jarvis status` checks
the voice stack; `bash scripts/setup-fallback.sh status` checks the local brain.
