#!/usr/bin/env python3
"""nb recall — search what you and your agents actually did.

  recall.py "<query>" [--kind session|commit] [--project X] [--days N] [--limit N]
  recall.py --index [--full]        rebuild (incremental unless --full)
  recall.py --open <ref>            print one chunk in full

Over the corpus that justifies retrieval: ~475 MB of run transcripts and ~3,000
commits across the repos under ~/Projects. Deliberately NOT the wiki — that is
~40K tokens, fits a context window five times over, and indexing it would drag
stale.py's superseded-memory problem into the ranker for no benefit.

SQLite FTS5, not embeddings, because the queries this corpus answers are lexical:
"when did I last touch gcalendar.py", "that NB_CHECK PATH thing", error strings,
flag names. BM25 beats vectors at exact-identifier match, which is most of it.
Zero new dependencies, and a vector rerank later is purely additive.

Transcripts and commits are append-only DATED RECORDS, which is what keeps the
superseded-memory problem manageable: a June transcript saying "the Ollama
fallback retries on cap" is a true statement about June. The danger is a reader
treating history as current state, so every result leads with its date and kind,
ranking decays with age, and anything consuming this is told: transcripts are
history; if they disagree with the code or the wiki, those win.
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/lib")
import transcripts as T  # noqa: E402

B, D, G, Y, X = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[0m"
DB = os.path.join(T.ROOT, "tasks", ".recall.db")
CODE_ROOT = os.path.expanduser(os.environ.get("NB_CODE_ROOT", "~/Projects"))
MAX_CHUNK = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
  id INTEGER PRIMARY KEY, kind TEXT, ref TEXT UNIQUE, ts TEXT,
  project TEXT, title TEXT, body TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
  title, body, content='docs', content_rowid='id',
  tokenize='porter unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS sources(path TEXT PRIMARY KEY, mtime REAL, size INT);
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
  INSERT INTO docs_fts(rowid,title,body) VALUES (new.id,new.title,new.body); END;
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
  INSERT INTO docs_fts(docs_fts,rowid,title,body) VALUES('delete',old.id,old.title,old.body); END;
"""


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    return c


# ── indexing ─────────────────────────────────────────────────────────────────
def _is_preamble(text):
    """Every headless transcript opens with the operator prompt, which embeds
    OVERVIEW.md and hermes/MEMORY.md verbatim. Index that and EVERY query matches
    EVERY session. Biggest single quality lever in the whole file."""
    head = text[:600]
    return any(sig in head for sig, _ in T._JOB_SIGNATURES) or "YOUR SPECIALIST TEAM" in head


def _turns(path):
    """One document per assistant turn, with the tool CALLS it made.

    Turn-level, not session-level: a 400 KB transcript as a single document is
    unretrievable — every query matches it and the snippet is meaningless.

    Tool CALLS, not tool RESULTS. A Read of a 3000-line file is retrievable from
    the file itself; storing it would bloat the index by an order of magnitude
    for content that is already on disk.
    """
    sid = os.path.basename(path)[:-6]
    cwd = ts = ""
    n = 0
    for line in T._lines(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        cwd = cwd or d.get("cwd") or ""
        ts = d.get("timestamp") or ts
        if d.get("type") != "assistant":
            continue
        m = d.get("message") or {}
        parts = []
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                parts.append(b.get("text") or "")
            elif b.get("type") == "tool_use":
                inp = b.get("input") or {}
                hint = (inp.get("file_path") or inp.get("path") or inp.get("command")
                        or inp.get("pattern") or inp.get("query") or inp.get("url") or "")
                parts.append(f"[{b.get('name')}] {str(hint)[:300]}")
        body = "\n".join(p for p in parts if p).strip()
        if not body or _is_preamble(body):
            continue
        n += 1
        yield {"kind": "session", "ref": f"{sid}#{n}", "ts": (ts or "")[:19],
               "project": os.path.basename(cwd) or "-",
               "title": f"{os.path.basename(cwd) or '-'} session",
               "body": body[:MAX_CHUNK]}


def index_transcripts(c, full):
    seen = {r[0]: (r[1], r[2]) for r in c.execute("SELECT path,mtime,size FROM sources")}
    added = skipped = 0
    for path, mt in T.iter_transcripts(None):
        try:
            sz = os.path.getsize(path)
        except OSError:
            continue
        if not full and seen.get(path) == (mt, sz):
            skipped += 1
            continue
        c.execute("DELETE FROM docs WHERE kind='session' AND ref LIKE ?",
                  (os.path.basename(path)[:-6] + "#%",))
        for doc in _turns(path):
            try:
                c.execute("INSERT OR REPLACE INTO docs(kind,ref,ts,project,title,body)"
                          " VALUES(:kind,:ref,:ts,:project,:title,:body)", doc)
                added += 1
            except sqlite3.Error:
                pass
        c.execute("INSERT OR REPLACE INTO sources VALUES(?,?,?)", (path, mt, sz))
    return added, skipped


def _repos():
    out = []
    for d in glob.glob(os.path.join(CODE_ROOT, "*")) + glob.glob(os.path.join(CODE_ROOT, "*", "*")):
        if os.path.isdir(os.path.join(d, ".git")):
            out.append(d)
    return out


def index_commits(c, full):
    added = 0
    for repo in _repos():
        name = os.path.basename(repo)
        since = []
        if not full:
            row = c.execute("SELECT max(ts) FROM docs WHERE kind='commit' AND project=?",
                            (name,)).fetchone()
            if row and row[0]:
                since = ["--since", row[0]]
        try:
            # \x02 LEADS each record and \x03 ends its header. --name-only emits
            # the file list AFTER the format string, so a trailing-only delimiter
            # made every record after the first parse the PREVIOUS commit's file
            # list as its header — 1222 commits indexed as 10. And %b contains
            # newlines, so the header cannot be delimited by one.
            log = subprocess.run(
                ["git", "-C", repo, "log", *since, "--no-merges",
                 "--format=%x02%H%x01%aI%x01%s%x01%b%x03", "--name-only"],
                capture_output=True, text=True, timeout=120).stdout
        except Exception:
            continue
        for rec in log.split("\x02"):
            if not rec.strip():
                continue
            head, _, files = rec.partition("\x03")
            bits = head.split("\x01")
            if len(bits) < 3:
                continue
            sha, when, subj = bits[0], bits[1], bits[2]
            body = (bits[3] if len(bits) > 3 else "") + "\n" + files
            try:
                c.execute("INSERT OR REPLACE INTO docs(kind,ref,ts,project,title,body)"
                          " VALUES('commit',?,?,?,?,?)",
                          (f"{name}@{sha[:10]}", when[:19], name, subj, body[:MAX_CHUNK]))
                added += 1
            except sqlite3.Error:
                pass
    return added


# ── query ────────────────────────────────────────────────────────────────────
def build_recall_sql(query, kind=None, project=None, days=None, limit=10):
    """Pure: returns (sql, params). No DB handle, so the query SHAPE is testable
    without a database — the part most likely to have bugs. Filter first (kind,
    project, date window), rank second, as a production retrieval pipeline does.

    Rank is bm25 scaled by recency. bm25() returns NEGATIVE numbers where more
    negative is a better match, so the decay divides rather than multiplies.
    """
    where, params = ["docs_fts MATCH ?"], [query]
    if kind:
        where.append("d.kind = ?"); params.append(kind)
    if project:
        where.append("d.project = ?"); params.append(project)
    if days:
        cut = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
        where.append("d.ts >= ?"); params.append(cut)
    sql = (f"SELECT d.kind, d.ref, d.ts, d.project, d.title,"
           f" snippet(docs_fts, 1, '[', ']', '…', 14) AS snip,"
           f" bm25(docs_fts) / (1.0 + (julianday('now') - julianday(d.ts)) / 180.0) AS rank"
           f" FROM docs_fts JOIN docs d ON d.id = docs_fts.rowid"
           f" WHERE {' AND '.join(where)} ORDER BY rank LIMIT ?")
    return sql, [*params, limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--full", action="store_true", help="with --index: rebuild everything")
    ap.add_argument("--open", dest="ref", help="print one chunk in full")
    ap.add_argument("--kind", choices=("session", "commit"))
    ap.add_argument("--project")
    ap.add_argument("--days", type=int)
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    c = db()

    if a.index:
        t0 = time.time()
        if a.full:
            c.execute("DELETE FROM docs"); c.execute("DELETE FROM sources")
        n1, skip = index_transcripts(c, a.full)
        n2 = index_commits(c, a.full)
        c.commit()
        tot = c.execute("SELECT count(*) FROM docs").fetchone()[0]
        print(f"{G}indexed{X} +{n1} turns · +{n2} commits · {skip} files unchanged "
              f"· {tot} docs total · {time.time()-t0:.1f}s")
        return 0

    if a.ref:
        r = c.execute("SELECT kind,ts,project,title,body FROM docs WHERE ref=?", (a.ref,)).fetchone()
        if not r:
            print(f"{Y}no such ref{X}"); return 1
        print(f"\n{B}{r[3]}{X}  {D}{r[0]} · {r[1]} · {r[2]}{X}\n\n{r[4]}\n")
        return 0

    if not a.query:
        n = c.execute("SELECT count(*) FROM docs").fetchone()[0]
        print(f"usage: nb recall \"<query>\"   ({n} docs indexed; 'nb recall --index' to refresh)")
        return 1

    sql, params = build_recall_sql(a.query, a.kind, a.project, a.days, a.limit)
    try:
        rows = c.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        print(f"{Y}bad query{X}: {e}"); return 1
    if not rows:
        print(f"{D}nothing matched{X}")
        return 0
    print()
    for kind, ref, ts, project, title, snip, _ in rows:
        snip = re.sub(r"\s+", " ", snip or "").strip()
        # date and kind FIRST: these are historical records, and a reader that
        # forgets that will treat a June decision as current state
        print(f"  {D}{ts[:10]}{X} {G}{kind:7}{X} {project[:18]:18} {snip[:110]}")
        print(f"  {D}{'':10} {'':7} {'':18} {ref}{X}")
    print(f"\n  {D}full chunk: nb recall --open <ref>{X}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
