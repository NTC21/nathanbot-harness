#!/usr/bin/env python3
"""lastdue.py — print the most recent scheduled occurrence at or before now.

Mirrors the subset of launchd's StartCalendarInterval that nathanbot uses:

    --hour H --minute M                 daily
    --hour H --minute M --weekday N     weekly (0=Sunday, launchd's numbering)
    --hour H --minute M --day N         monthly, on day-of-month N

Prints an ISO-8601 local timestamp. Exits 1 if no occurrence has happened yet
(e.g. a monthly job on the 1st, queried before this month's first firing and
with no prior month in range) so the caller can treat it as "not due".
"""
import argparse
import sys
from datetime import datetime, timedelta

p = argparse.ArgumentParser()
p.add_argument("--hour", type=int, required=True)
p.add_argument("--minute", type=int, default=0)
p.add_argument("--weekday", default="-")   # "-" or 0..6, 0=Sunday
p.add_argument("--day", default="-")       # "-" or 1..31
a = p.parse_args()

weekday = None if a.weekday in ("-", "") else int(a.weekday)
day = None if a.day in ("-", "") else int(a.day)

now = datetime.now()


def matches(d):
    # datetime.weekday() is Mon=0; launchd is Sun=0
    if weekday is not None and (d.weekday() + 1) % 7 != weekday:
        return False
    if day is not None and d.day != day:
        return False
    return True


# Walk back day by day from today to the newest matching firing <= now.
# 40 days covers daily, weekly, and every month length.
for back in range(0, 40):
    d = (now - timedelta(days=back)).replace(
        hour=a.hour, minute=a.minute, second=0, microsecond=0
    )
    if d <= now and matches(d):
        print(d.isoformat(timespec="seconds"))
        sys.exit(0)

sys.exit(1)
