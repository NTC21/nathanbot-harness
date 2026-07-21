# START HERE — first run

New here? This gets nathanbot working on your machine in a few minutes.

## 1. Copy the example configs
Real config is gitignored; the repo ships templates with placeholder values. Copy each one and
fill in your details.
```bash
for f in config/*.example.json; do cp "$f" "${f%.example.json}.json"; done
```
Then edit the copies — most importantly `config/accounts.json` (your email identities) and
`config/paths.json` (machine paths).

## 2. Set up secrets
Secrets never go in the repo. Create a private vault and keep tokens/keys there.
```bash
mkdir -p ~/.secrets && chmod 700 ~/.secrets
```
`.env.example` lists the variable names your environment expects — copy it to `.env` (untracked)
and point values at your vault.

## 3. Put `nb` on your PATH (optional)
```bash
echo 'export PATH="$PWD/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

## 4. Connect email / calendar (optional)
If you want the assistant to read/draft mail or manage calendar, configure your identities in
`config/accounts.json`: list each identity and mark exactly one as the authorized default. The
rest stay not-authorized until you explicitly enable them.

## 5. Run the dashboard
```bash
cd ui && npm install && npm run dev
```

## The daily loop
```bash
nb add "whatever just occurred to you"    # capture. never blocks. do this constantly.
nb triage                                  # AI files everything into real tasks
nb next                                    # what to work on now
nb run                                     # execute ready tasks in parallel
```

## When you want to see state
```bash
nb brief      # what's next, what's waiting, system health
nb status     # ready / blocked / needs-decision counts
nb decide     # resolve the needs-decision pile (approve/defer/drop)
```

## Running on its own (optional scheduled tasks)
Example schedule if you wire up cron/an always-on box:
- `brief`  daily — notification + written brief
- `tidy`   weekly — maintenance report, changes nothing
- `evolve` weekly — proposes improvements to itself
- `scout`  monthly — researches new tools

Configure these so nothing scheduled pushes code, merges, or sends email without your approval.

## Capabilities (what the assistant knows where)
```bash
nb profile list                  # all capability layers
nb profile show <path>           # what a project resolves to
nb profile sync                  # re-apply after editing config/profiles.json
```
Edit `capabilities/<name>.yaml` to teach it something once, everywhere.

## Email/calendar — READ THIS
Configure your authorized sending identity in `config/accounts.json`. The assistant must state
which account it's acting as before drafting, and never sends without your explicit confirmation
of both the text and the account. Sending from the wrong identity is unrecoverable — approval is
required every time.

## Where things live
- `AGENTS.md` — the contract every AI harness reads
- `shared-memory/OVERVIEW.md` — always-loaded core (kept under ~2000 chars)
- `wiki/pages/` — durable knowledge; open `wiki/` as an Obsidian vault for the graph. `owner.md` is the self-page.
- `config/accounts.json` — email identities (one authorized default)
- `config/projects.json` — per-project autonomy (auto-merge / auto-pr / review-required)
- `config/profiles.json` — which capabilities each project gets
