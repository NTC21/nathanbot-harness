# Claude Code Guidance

Read `AGENTS.md` — it is the canonical entry doc for this repo (memory routing, write-back rules, repo map, working style). Everything that governs how to work here lives there, not in this file.

Claude-specific config only lives in `.claude/` — the subagent definitions in `.claude/agents/`.
The PreToolUse guards live in `claude-hooks/`; run `claude-hooks/install.sh` to wire them into
your Claude settings.
