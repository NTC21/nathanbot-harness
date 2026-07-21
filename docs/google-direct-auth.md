# Direct Google integration — design

Bypasses claude.ai connectors (one account per service) so all of your identities work
simultaneously, from any harness, with credentials in your own vault.

## Decisions (locked 2026-07-21)
| Decision | Choice | Why |
|---|---|---|
| Publishing status | **In production** | Testing mode expires refresh tokens after 7 days — would silently kill cron jobs |
| Scopes | **gmail.modify** + calendar | Labeling/triage already assumed by the business-ops capability |
| Client type | Desktop app (loopback) | No hosted redirect needed |
| Domains | Regular Gmail + custom domain | No Workspace admin step |

## Scopes requested
```
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.settings.basic     (read send-as aliases)
https://www.googleapis.com/auth/calendar
```
Scopes bake into every token — changing them means re-consenting every account.

## Accounts vs aliases
`you@company.com` and `you@product.com` are custom-domain addresses on regular
Gmail, which usually means they are **send-as aliases**, not separate Google accounts.

`auth.py login` detects which:
- separate Google account -> its own token file
- send-as alias -> no token; recorded under the owning account's `aliases`

`gmail.py send --account work` resolves to either a distinct token or an alias on another
account. Callers don't need to know which.

## Token layout
```
~/.secrets/google/
  client_secret.json        # OAuth client (600)
  personal.json             # refresh token
  work.json
  <key>.json                # one per REAL account
  aliases.json              # alias -> owning account map
```
Directory 700, files 600. Never in git.

## Safety contract
- `send` takes a **draft id only** — it cannot compose. Draft -> human -> send is the only path.
- `--yes <account-key>` must restate the account. A bare `--yes` is too easy to add reflexively;
  a wrong-account send requires typing the wrong account twice.
- `login` hard-fails if the consented email != the requested account. Google's account chooser
  makes consenting as the wrong logged-in account easy, and it fails silently forever after.
- Every command prints `Acting as: <email>` before doing anything.

## Setup (~15 min, one time)
1. console.cloud.google.com -> new project "nathanbot"
2. Enable **Gmail API** and **Google Calendar API**
3. OAuth consent screen -> External -> **Publish (In production)**
4. Credentials -> Create OAuth client ID -> **Desktop app** -> download JSON
5. Save as `~/.secrets/google/client_secret.json`
6. `nb mail login personal` (repeat per account — browser opens, approve)
