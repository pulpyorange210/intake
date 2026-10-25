"""Optional daily Slack summary: forms processed, flagged and approved, and the median entry time.

  python -m server.daily_summary            # print today's summary (UTC)
  python -m server.daily_summary --send     # post it (webhook if SLACK_WEBHOOK_URL is set, else the outbox)

Off unless you schedule it, e.g. a cron entry at 18:00: `python -m server.daily_summary --send`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from .config import Settings
from .db import Database
from .slack import daily_summary_payload, make_notifier, post_with_retry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=dt.datetime.now(dt.timezone.utc).date().isoformat(), help="YYYY-MM-DD (UTC)")
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()
    settings = Settings.from_env()
    payload = daily_summary_payload(Database(settings.db_path), args.day)
    if args.send:
        post_with_retry(make_notifier(settings), payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
