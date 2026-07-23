#!/usr/bin/env python3
"""Proactive calendar nudge — nathanbot pings YOU before an event starts, so you
don't have to check. Runs every ~10 min (launchd). Each event nudges once (dedup).

  NB_NUDGE_MIN   how many minutes ahead to warn (default 30)
Push goes through deliver.sh -> every configured channel, incl. Telegram.
"""
import json, os, sys, subprocess, pathlib
from datetime import datetime, timezone, timedelta

R = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / "scripts" / "google"))
import auth            # noqa: E402
import gcalendar as gc  # noqa: E402

NUDGE_MIN = int(os.environ.get("NB_NUDGE_MIN", "30"))
STATE = R / "tasks" / ".nudged.json"


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d):
    try:
        STATE.write_text(json.dumps(d))
    except Exception:
        pass


def deliver(title, body):
    subprocess.run([str(R / "scripts" / "deliver.sh"), title, body],
                   timeout=30, capture_output=True)


def main():
    now = datetime.now(timezone.utc)
    seen = {k: v for k, v in _load().items()
            if v > (now - timedelta(hours=3)).timestamp()}   # prune stale
    for k in auth.accounts_cfg():
        try:
            _email, items = gc.list_events(k, days=1)
        except (SystemExit, Exception):     # unauthorized account raises SystemExit
            continue
        for ev in items:
            sd = ev.get("start", {}).get("dateTime")
            if not sd:
                continue                       # all-day events don't nudge
            try:
                start = datetime.fromisoformat(sd).astimezone(timezone.utc)
            except ValueError:
                continue
            mins = (start - now).total_seconds() / 60
            if 0 < mins <= NUDGE_MIN:
                key = ev.get("id") or (ev.get("summary", "") + sd)
                if key in seen:
                    continue
                seen[key] = now.timestamp()
                deliver(f"⏰ In {int(round(mins))} min",
                        f"{ev.get('summary', '(event)')}  [{k}]")
    _save(seen)


if __name__ == "__main__":
    main()
