# Telegram — the two-way phone channel

nathanbot texts you and you text back, from anywhere. Your messages route to the same
operator the CLI uses (all its safety fuses apply); email-send approvals arrive as
inline **Approve / Cancel** buttons. Telegram holds messages ~24h server-side, so anything
you send while the Mac sleeps is processed when it wakes. $0, no VPS.

## One-time setup (~2 min)
1. **Create the bot.** In Telegram, message **@BotFather** → `/newbot` → follow prompts →
   copy the token it gives you.
2. **Store the token** (vault, never the repo):
   ```
   mkdir -p ~/.secrets/telegram && chmod 700 ~/.secrets/telegram
   printf '%s' '<TOKEN>' > ~/.secrets/telegram/bot_token && chmod 600 ~/.secrets/telegram/bot_token
   ```
3. **Get your chat id.** Run `nb tg --whoami`, then send your bot any message. It prints your
   `chat_id` and the exact line to save it (only this id is ever answered — others are ignored).
4. **Run it always-on:** `nb schedule install-telegram` (KeepAlive launchd job).

## Use
- Text the bot anything → it acts and replies (`nb add`, questions, "what's ready", etc.).
- "send my latest draft" → you get an Approve/Cancel card; tap Approve to send.
- Briefs + alerts also push here automatically (deliver.sh channel 4).

## Commands
- `nb tg` — run the listener in the foreground (testing).
- `nb tg --whoami` — capture your chat id.
- `nb tg --once` — process one batch and exit.
- `nb schedule install-telegram` / `nb schedule remove` — start/stop the always-on job.

## Notes
- The listener talks to the local API server (`http://127.0.0.1:7777`), which stays running as
  the headless brain/API — day-to-day use never needs a computer.
- Sleep caveat: the Mac still has to wake to process. Telegram queues up to 24h, so brief sleeps
  are fine; a Mac off all day won't reply until it's back.
