#!/usr/bin/env bash
# news.sh — the owner's tech/AI news brief. Pulls the important developments in his
# space, distilled to short punchy bullets with source links. On demand or scheduled.
#
#   nb news              print the brief
#   nb news --deliver    also push it to your phone (Telegram + any channel)
#
# Topics live in config/news-topics.txt (edit anytime).
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE="$R/bin/claudew"
deliver=0; [ "${1:-}" = "--deliver" ] && deliver=1

topics="$(grep -vE '^\s*#|^\s*$' "$R/config/news-topics.txt" 2>/dev/null | paste -sd'; ' -)"
[ -z "$topics" ] && topics="AI, software engineering, developer tools, tech"

# fresh, real candidates from high-signal free sources (HN, Show HN, arXiv,
# Lobsters, pinned feeds). Already-delivered items are filtered out upstream.
cands="$(python3 "$R/scripts/news/fetch.py" \
          --hours "${NB_NEWS_HOURS:-24}" \
          --fallback-hours "${NB_NEWS_FALLBACK_HOURS:-48}" \
          --min-velocity "${NB_NEWS_MINVEL:-4}" 2>/dev/null)"

prompt="You are the owner's news scout — a solo builder in AI/software. Below are FRESH candidate items
pulled just now from high-signal sources (Hacker News front-page, Show HN = new tools, arXiv = new
research, Lobsters). Your job: curate, do not invent.

HIS INTERESTS (rank by these):
$topics

CANDIDATE ITEMS (only use these + anything you verify by fetching their links):
$cands

Each candidate is tagged [source|topic|AGE] where AGE is hours since publication.

Give him a brief he reads in 30 seconds:
- Pick the 5 to 8 highest-signal items for a solo AI/software builder. Deliberately mix MAJOR news
  (model/tool releases, big funding, policy that hits builders) WITH non-obvious/emerging things
  (a sharp Show HN tool, a notable new paper, a niche post) he probably hasn't seen. Skip generic filler.
- BE EARLY. Between two items of similar value, always take the younger one — he wants to hear things
  first, not confirmed. An item under 6h old is worth including at a slightly lower bar. An item over
  24h old must clearly earn its slot, because he has likely already seen it elsewhere.
- Items tagged 'other' are off-topic for him by default; include one only if it is genuinely major.
- EACH item is ONE line: punchy plain-English headline, a dash, a short clause on why it matters to
  him, then the source URL from the candidate in parentheses. No markdown, no nested bullets, no preamble.
- Use WebFetch to confirm/enrich an item if the title is thin. Never fabricate — every line maps to a
  real candidate above (or something you fetched). Always include the working link.

Format each line exactly like:
Headline here - why it matters (https://source-url)"

# stdout ONLY, and the exit code is checked. This used to capture 2>&1 and ignore
# rc, so claudew's own stderr line — "claudew: Claude usage is capped — this run did
# not complete." — became the body of the 08:00 📰 brief. A failed run must fail, not
# get delivered as news.
out="$(NB_JOB=news "$CLAUDE" -p "$prompt" --allowedTools "WebSearch" "WebFetch" "Read")"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "news.sh: claudew exited $rc — no brief produced, nothing delivered." >&2
  exit "$rc"
fi

# strip any stray ANSI, trim
out="$(printf '%s' "$out" | sed $'s/\033\\[[0-9;]*m//g')"
printf '%s\n' "$out"

if [ "$deliver" -eq 1 ] && [ -n "${out// }" ]; then
  "$R/scripts/deliver.sh" "📰 Tech/AI brief" "$out" >/dev/null 2>&1 || true
  # Record what went out so tomorrow's brief can't repeat it. Only on delivery —
  # a bare `nb news` preview shouldn't burn items you never actually received.
  printf '%s' "$out" | python3 "$R/scripts/news/fetch.py" --mark 2>/dev/null || true
fi
