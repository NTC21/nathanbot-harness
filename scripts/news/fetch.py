#!/usr/bin/env python3
"""Pull fresh candidate items from high-signal, free, no-key sources, so the news
brief is grounded in REAL timestamped items (not whatever web search guesses).

Sources: Hacker News + Show HN (Algolia), arXiv, Lobste.rs, and the pinned feeds
in config/news-feeds.txt. Each source is best-effort — a failure yields fewer
items, never a crash.

Three things make the brief early rather than merely recent:

  1. Every candidate carries its AGE. The curator can't prefer breaking news if
     it can't tell a 3h-old item from a 47h-old one.
  2. HN is ranked by VELOCITY (points/hour), not absolute points. Points accrue
     with age, so a fixed points bar is an age filter in disguise — it
     systematically hides the young stories you actually want.
  3. A 24h primary window, with a 48h fallback reserved for items that clear a
     high bar. Thin news days still fill; ordinary days stay fresh.

And the sent-history (tasks/state/news-seen.json) stops repeats, which is what
makes wide windows safe for low-frequency feeds.

  fetch.py [--hours N] [--fallback-hours N] [--min-velocity V]
  fetch.py --mark            record URLs from a delivered brief on stdin
"""
import json, os, sys, re, argparse, time, urllib.request, urllib.parse
import concurrent.futures as futures

UA = {"User-Agent": "nathanbot-news/2.0"}
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SEEN_PATH = os.path.join(ROOT, "tasks", "state", "news-seen.json")
SEEN_KEEP_DAYS = 30
BUCKETS = ("ai", "dev", "startup", "other")

# HN's front page is general-interest: on any given day it carries climate,
# history and supermarket-payment stories alongside the tech. Those aren't in
# the topics file, so they get classified into "other" and held to a small
# share — big off-topic news can still surface, but it can't eat the AI slots.
LEXICON = {
    "ai": ("ai", "a.i.", "llm", "llms", "gpt", "claude", "anthropic", "openai",
           "gemini", "deepmind", "mistral", "llama", "qwen", "deepseek",
           "inference", "agent", "agents", "agentic", "rag", "embedding",
           "embeddings", "transformer", "diffusion", "neural", "rl",
           "reinforcement learning", "machine learning", "fine-tuning",
           "finetuning", "prompt", "prompting", "hugging face", "pytorch",
           "tensor", "chatbot", "copilot", "cursor", "token", "tokens",
           "tokenizer", "multimodal", "model", "models", "benchmark",
           "open-weight", "context window", "training"),
    # no bare "go" — it's too common a verb to use as a language signal
    "dev": ("rust", "golang", "python", "typescript", "javascript",
            "compiler", "kernel", "linux", "postgres", "sqlite", "database",
            "framework", "library", "git", "docker", "kubernetes", "cli",
            "editor", "vim", "emacs", "debugging", "wasm", "webassembly",
            "protocol", "api", "open source", "browser", "runtime",
            "package manager", "type system", "latency", "throughput",
            "regression", "refactor", "release", "changelog", "cve",
            "vulnerability", "exploit", "security", "parser", "lint", "linter",
            "formatter", "static analysis", "type checker", "ruff", "uv",
            "npm", "cargo", "pip", "build system", "dependency", "ci", "sdk"),
    "startup": ("funding", "raises", "raised", "series a", "series b", "series c",
                "seed round", "valuation", "acquisition", "acquires", "acquired",
                "ipo", "y combinator", "venture", "vc", "arr", "founder",
                "founders", "layoff", "layoffs", "startup", "startups"),
}

# Whole-word matching, not substring: "ai" must not fire on "airport", "email"
# or "mountain", "rag" on "storage", "cli" on "climate", "arr" on "array".
# Substring matching filed a robotic-parking story under AI.
_LEX_RE = {b: re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" %
                         "|".join(sorted((re.escape(w) for w in ws), key=len, reverse=True)))
           for b, ws in LEXICON.items()}


def classify(title, url=""):
    """Best-matching bucket for an item that didn't come with one declared."""
    hay = f"{title} {url}".lower()
    best, best_n = "other", 0
    for bucket, rx in _LEX_RE.items():
        n = len(set(rx.findall(hay)))
        if n > best_n:
            best, best_n = bucket, n
    return best


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _now():
    return int(time.time())


# ── sent-history ────────────────────────────────────────────────────────────
# Without this, a 48h window on a daily brief guarantees ~50% overlap, and any
# feed window wider than the brief interval repeats every single day.

TRACKING = re.compile(r"^(utm_|ref$|ref_|source$|fbclid$|gclid$|mc_)")


def norm_url(u):
    """Canonical form for dedupe: scheme/www/tracking-param/trailing-slash blind."""
    try:
        p = urllib.parse.urlsplit(u.strip())
    except ValueError:
        return u.strip().lower()
    host = re.sub(r"^www\.", "", p.netloc.lower())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not TRACKING.match(k)]
    path = p.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(("", host, path, urllib.parse.urlencode(sorted(q)), ""))


def norm_title(t):
    """Loose title key so the same story from 3 outlets collapses to one."""
    t = re.sub(r"^(show hn|ask hn|tell hn):\s*", "", t.strip().lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())[:70]


def load_seen():
    try:
        with open(SEEN_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    cut = _now() - SEEN_KEEP_DAYS * 86400
    return {k: v for k, v in data.items() if isinstance(v, int) and v > cut}


def mark_seen(text):
    """Record every URL in a delivered brief so it never comes back."""
    seen = load_seen()
    now = _now()
    n = 0
    for u in re.findall(r"https?://[^\s)\]]+", text):
        k = norm_url(u)
        if k not in seen:
            n += 1
        seen[k] = now
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    tmp = SEEN_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(seen, f)
    os.replace(tmp, SEEN_PATH)          # atomic; a crash can't truncate history
    print(f"marked {n} new url(s); {len(seen)} tracked", file=sys.stderr)


# ── sources ─────────────────────────────────────────────────────────────────

def hn(now, fresh_cut, fall_cut, min_vel):
    """Two-tier HN. Fresh tier uses a low points bar and ranks by velocity, so a
    3h-old story at 40 pts (13/h) outranks a 40h-old story at 200 pts (5/h).
    Fallback tier only admits items that already proved themselves."""
    base = "https://hn.algolia.com/api/v1/search_by_date"
    out = []

    def pull(tag, cut, min_pts, n, bucket, vel_floor):
        q = (f"{base}?tags={tag}&numericFilters=points>{min_pts},created_at_i>{cut}"
             f"&hitsPerPage={n}")
        for h in json.loads(_get(q)).get("hits", []):
            u = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
            age = max((now - h.get("created_at_i", now)) / 3600.0, 0.5)
            pts = h.get("points", 0) or 0
            vel = pts / age
            if vel < vel_floor:
                continue
            fam = "HN" if tag == "story" else "ShowHN"
            title = h.get("title", "")
            # HN carries no topic metadata, so infer it; Show HN is a tool
            # launch by definition, so fall back to dev rather than "other"
            b = classify(title, u)
            if b == "other" and bucket == "dev":
                b = "dev"
            out.append(dict(src=fam, family=fam,
                            title=title, url=u, bucket=b,
                            age=age, score=vel,
                            meta=f"{pts}pts {vel:.0f}/h"))

    for label, args in (
        ("hn-fresh",  ("story",   fresh_cut, 15,  40, "ai",  min_vel)),
        ("hn-strong", ("story",   fall_cut,  150, 20, "ai",  0.0)),
        ("show-hn",   ("show_hn", fresh_cut, 3,   20, "dev", 0.0)),
    ):
        try:
            pull(*args)
        except Exception as e:
            print(f"({label}: {e})", file=sys.stderr)
    return out


def arxiv(now, cut):
    cats = "cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL"
    url = ("https://export.arxiv.org/api/query?search_query=" + cats +
           "&sortBy=submittedDate&sortOrder=descending&max_results=25")
    out = []
    try:
        xml = _get(url, timeout=20)
    except Exception as e:
        print(f"(arxiv: {e})", file=sys.stderr)
        return out
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        t = re.search(r"<title>(.*?)</title>", entry, re.S)
        link = re.search(r"<id>(.*?)</id>", entry, re.S)
        if not (t and link):
            continue
        ep = _date_epoch(entry)             # was unfiltered before: papers of any age
        if ep is not None and ep < cut:
            continue
        age = (now - ep) / 3600.0 if ep else 24.0
        out.append(dict(src="arXiv", family="arXiv",
                        title=re.sub(r"\s+", " ", t.group(1)).strip(),
                        url=link.group(1).strip(), bucket="ai", age=age,
                        score=1.0, meta="paper"))
    return out


LOBSTER_TAGS = {"ai": "ai", "ml": "ai", "programming": "dev", "devops": "dev",
                "rust": "dev", "go": "dev", "python": "dev", "security": "dev"}


def lobsters(now, cut, tag, bucket):
    """One tag per call — lobste.rs rate-limits, and fetching eight tags inside a
    single worker meant one slow tag stalled the whole run."""
    out = []
    try:
        rows = json.loads(_get(f"https://lobste.rs/t/{tag}.json", timeout=8))
    except Exception as e:
        print(f"(lobsters {tag}: {e})", file=sys.stderr)
        return out
    for s in rows[:8]:
        ep = _iso_epoch(s.get("created_at", ""))
        if ep is not None and ep < cut:     # was unfiltered before
            continue
        age = (now - ep) / 3600.0 if ep else 24.0
        sc = s.get("score", 0) or 0
        out.append(dict(src="Lobsters", family="Lobsters", title=s.get("title", ""),
                        url=s.get("url") or s.get("short_id_url", ""),
                        bucket=bucket, age=age,
                        score=sc / max(age, 1.0), meta=f"{sc}pts"))
    return out


# ── pinned feeds ────────────────────────────────────────────────────────────

def _feeds(path):
    """Parse [bucket] sections and optional '@hours' per-feed window overrides."""
    out, bucket = [], "ai"
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return out
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.fullmatch(r"\[(\w+)\]", ln)
        if m:
            bucket = m.group(1) if m.group(1) in BUCKETS else "ai"
            continue
        parts = ln.split()
        hours = None
        if len(parts) > 1 and parts[1].startswith("@"):
            try:
                hours = int(parts[1][1:])
            except ValueError:
                hours = None
        out.append((parts[0], bucket, hours))
    return out


def _tag(name, block):
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
    if not m:
        return ""
    t = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S)
    return re.sub(r"<[^>]+>", "", t).strip()


def _link(block):
    m = re.search(r'<link[^>]*href="([^"]+)"', block)        # Atom
    if m:
        return m.group(1).strip()
    m = re.search(r"<link>(.*?)</link>", block, re.S)          # RSS
    return m.group(1).strip() if m else ""


def _iso_epoch(v):
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return None


def _date_epoch(block):
    import email.utils
    for tag in ("pubDate", "published", "updated", "dc:date"):
        v = _tag(tag, block)
        if not v:
            continue
        try:
            return int(email.utils.parsedate_to_datetime(v).timestamp())
        except (TypeError, ValueError, OverflowError):
            pass
        ep = _iso_epoch(v)
        if ep is not None:
            return ep
    return None


def one_feed(url, bucket, hours, now, default_cut, per_feed=4):
    cut = now - hours * 3600 if hours else default_cut
    try:
        xml = _get(url, timeout=10)
    except Exception as e:
        print(f"(rss {url}: {e})", file=sys.stderr)
        return []
    src = re.sub(r"^www\.", "", urllib.parse.urlparse(url).netloc) or "rss"
    blocks = (re.findall(r"<item[ >].*?</item>", xml, re.S) +
              re.findall(r"<entry[ >].*?</entry>", xml, re.S))
    items = []
    for b in blocks:
        title, link = _tag("title", b), _link(b)
        if not title or not link:
            continue
        ep = _date_epoch(b)
        if ep is not None and ep < cut:
            continue
        age = (now - ep) / 3600.0 if ep else 48.0
        items.append(dict(src=src, family="feed", title=title, url=link,
                          bucket=bucket, age=age, score=1.0, meta="rss"))
    # newest first, then take the quota — feeds aren't all sorted newest-first,
    # so slicing raw order could hand back a feed's OLDEST qualifying posts
    items.sort(key=lambda i: i["age"])
    return items[:per_feed]


# ── assembly ────────────────────────────────────────────────────────────────

def dedupe(items, seen):
    """Collapse same-URL and same-story-different-outlet, drop already-sent."""
    by_url, by_title, out = set(), set(), []
    for it in sorted(items, key=lambda i: (i["age"], -i["score"])):
        if not it["title"] or not it["url"]:
            continue
        ku, kt = norm_url(it["url"]), norm_title(it["title"])
        if ku in seen or ku in by_url or (kt and kt in by_title):
            continue
        by_url.add(ku)
        if kt:
            by_title.add(kt)
        out.append(it)
    return out


# HN alone can return 40+ qualifying stories a day. Left uncapped it takes ~2/3
# of the pool and starves the sources that carry the non-obvious items — arXiv
# and the hand-picked feeds were getting squeezed to zero.
FAMILY_SHARE = {"HN": 0.30, "feed": 0.38, "ShowHN": 0.12,
                "Lobsters": 0.11, "arXiv": 0.09}


def _take(items, cap_of, key):
    """Greedy fill honouring per-key caps; returns (picked, leftovers)."""
    picked, spill, used = [], [], {}
    for it in items:
        k = key(it)
        if used.get(k, 0) < cap_of(k):
            used[k] = used.get(k, 0) + 1
            picked.append(it)
        else:
            spill.append(it)
    return picked, spill


def mix(items, total, ai_share=0.70):
    """Two passes. First bound each source family so none can flood the brief,
    then keep AI the majority while guaranteeing dev/startup reserved slots.
    Unused slots flow back rather than shrinking the pool."""
    by_family, fam_spill = _take(
        items, lambda f: max(1, int(total * FAMILY_SHARE.get(f, 0.10))),
        lambda i: i.get("family", "feed"))

    bucket_cap = {"ai": int(total * ai_share),
                  "dev": int(total * 0.20),
                  "startup": int(total * 0.10),
                  "other": max(2, int(total * 0.07))}
    picked, spill = _take(by_family, lambda b: bucket_cap.get(b, 0),
                          lambda i: i["bucket"])

    # Backfill only from bucket-overflow, which is still inside the family caps.
    # Never from fam_spill: refilling out of it would hand the slots straight
    # back to whichever source flooded, undoing the pass above. total is a
    # CEILING, not a quota — a genuinely quiet day should yield a shorter
    # candidate list, not a padded one.
    if len(picked) < total:
        picked += spill[:total - len(picked)]
    picked.sort(key=lambda i: (i["age"], -i["score"]))
    return picked[:total]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24, help="primary recency window")
    ap.add_argument("--fallback-hours", type=int, default=48,
                    help="wider window, high-signal items only")
    ap.add_argument("--min-velocity", type=float, default=4.0,
                    help="HN points/hour floor for the fresh tier")
    ap.add_argument("--max-items", type=int, default=55)
    ap.add_argument("--mark", action="store_true",
                    help="read a delivered brief on stdin, record its URLs as sent")
    a = ap.parse_args()

    if a.mark:
        mark_seen(sys.stdin.read())
        return

    now = _now()
    fresh_cut = now - a.hours * 3600
    fall_cut = now - a.fallback_hours * 3600
    feeds = _feeds(os.path.join(ROOT, "config", "news-feeds.txt"))

    # fetches are IO-bound and independent; serial was ~7s and this list is
    # nearly twice as long now. Every source returns its own list — nothing is
    # shared across threads.
    out = []
    with futures.ThreadPoolExecutor(max_workers=12) as ex:
        pending = [ex.submit(hn, now, fresh_cut, fall_cut, a.min_velocity),
                   ex.submit(arxiv, now, fall_cut)]
        pending += [ex.submit(lobsters, now, fresh_cut, t, b)
                    for t, b in LOBSTER_TAGS.items()]
        pending += [ex.submit(one_feed, u, b, h, now, fresh_cut) for u, b, h in feeds]
        for f in pending:
            try:
                out += f.result() or []
            except Exception as e:
                print(f"(source failed: {e})", file=sys.stderr)

    seen = load_seen()
    items = mix(dedupe(out, seen), a.max_items)

    kept = {b: sum(1 for i in items if i["bucket"] == b) for b in BUCKETS}
    print(f"# {len(items)} candidates | fresh<{a.hours}h, fallback<{a.fallback_hours}h "
          f"| mix " + " ".join(f"{b}={kept[b]}" for b in BUCKETS) + " "
          f"| {len(seen)} previously-sent items excluded")
    print("# AGE = hours since publication. Prefer the freshest unless an older "
          "item is clearly bigger news.")
    for i in items:
        print(f"[{i['src']}|{i['bucket']}|{i['age']:.0f}h] {i['title']} — "
              f"{i['url']} ({i['meta']})")


if __name__ == "__main__":
    main()
