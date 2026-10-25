"""Slack alert for flagged forms, via an incoming webhook.

One alert per form, ever: the `alert_sent` event is checked before sending and recorded after. Alerting never
blocks processing: it runs on the background worker after the form is already in the queue, and a Slack
outage is logged, not raised. Without SLACK_WEBHOOK_URL the message goes to a local outbox file instead.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Callable, List, Optional, Protocol

import httpx

from . import retry
from .db import Database, has_event, log_event

log = logging.getLogger(__name__)

MAX_REASONS = 3
REASON_CHARS = 280


class Notifier(Protocol):
    def post(self, payload: dict) -> None:
        """Send one message; raise retry.HTTPStatusError or a transport error on failure."""


class WebhookNotifier:
    def __init__(self, url: str, timeout: float = 10):
        self.url, self.http = url, httpx.Client(timeout=timeout)

    def post(self, payload: dict) -> None:
        response = self.http.post(self.url, json=payload)
        if response.status_code >= 400:
            raise retry.HTTPStatusError(response.status_code, response.text)


class OutboxNotifier:
    """Local stand-in when no webhook is configured: one JSON message per line."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def post(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(payload) + "\n")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _clip(text: str, n: int = REASON_CHARS) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def alert_payload(filename: str, form_id: int, flags: List[dict], base_url: str) -> dict:
    """Block Kit message: filename, flag counts per severity, up to 3 high-severity reasons, a review button."""
    counts = Counter(f["severity"] for f in flags)
    count_text = " · ".join(f"{counts[s]} {s}" for s in ("high", "medium", "low") if counts[s])
    icon = "🔴" if counts["high"] else "🟡"
    url = f"{base_url.rstrip('/')}/forms/{form_id}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
                                           "text": f"{icon} *{_escape(filename)}* needs review\n{count_text}"}}]
    high = [f["reason"] for f in flags if f["severity"] == "high"]
    if high:
        lines = [f"• {_escape(_clip(r))}" for r in high[:MAX_REASONS]]
        if len(high) > MAX_REASONS:
            lines.append(f"+{len(high) - MAX_REASONS} more")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*High severity*\n" + "\n".join(lines)}})
    blocks.append({"type": "actions", "elements": [{
        "type": "button", "text": {"type": "plain_text", "text": "Review form"}, "url": url, "style": "primary",
        "action_id": "open_review"}]})
    return {"text": f"{icon} {filename} needs review: {count_text}", "blocks": blocks}


def post_with_retry(notifier: Notifier, payload: dict, sleep: Callable[[float], None] = time.sleep) -> None:
    for attempt in range(1, retry.MAX_ATTEMPTS + 1):
        try:
            notifier.post(payload)
            return
        except Exception as exc:  # noqa: BLE001
            if not retry.is_retryable(exc) or attempt == retry.MAX_ATTEMPTS:
                raise
            sleep(retry.backoff(attempt))


def alert_for_form(db: Database, form_id: int, notifier: Notifier, base_url: str,
                   sleep: Callable[[float], None] = time.sleep) -> str:
    """Returns 'sent', 'clean', 'already_sent' or 'failed'. Never raises."""
    try:
        with db.connect() as conn:
            if has_event(conn, form_id, "alert_sent"):
                return "already_sent"
            form = conn.execute("SELECT filename FROM forms WHERE id = ?", (form_id,)).fetchone()
            flags = [dict(f) for f in conn.execute("SELECT * FROM flags WHERE form_id = ? ORDER BY id", (form_id,))]
        if form is None or not flags:
            return "clean"
        post_with_retry(notifier, alert_payload(form["filename"], form_id, flags, base_url), sleep)
        with db.transaction() as conn:
            log_event(conn, form_id, "alert_sent")
        return "sent"
    except Exception as exc:  # noqa: BLE001 - alerting must never stop a form from being reviewed
        log.error("slack alert for form %s failed: %s", form_id, exc)
        return "failed"


def daily_summary_payload(db: Database, day: str) -> dict:
    """Optional daily summary (`python -m server.daily_summary`): forms processed, flagged and approved on
    `day` (YYYY-MM-DD, UTC), and the median upload-to-approval time of the forms approved that day."""
    with db.connect() as conn:
        def count(sql: str) -> int:
            return conn.execute(sql, (f"{day}%",)).fetchone()[0]
        processed = count("SELECT COUNT(DISTINCT form_id) FROM events WHERE type = 'extracted' AND at LIKE ?")
        flagged = count("""SELECT COUNT(DISTINCT e.form_id) FROM events e WHERE e.type = 'extracted' AND e.at LIKE ?
                           AND EXISTS (SELECT 1 FROM flags f WHERE f.form_id = e.form_id)""")
        rows = conn.execute("""SELECT u.at AS up, a.at AS ap FROM events a JOIN events u
                               ON u.form_id = a.form_id AND u.type = 'uploaded'
                               WHERE a.type = 'approved' AND a.at LIKE ?""", (f"{day}%",)).fetchall()
    durations = [(dt.datetime.fromisoformat(r["ap"]) - dt.datetime.fromisoformat(r["up"])).total_seconds()
                 for r in rows]
    median: Optional[str] = None
    if durations:
        minutes = statistics.median(durations) / 60
        median = f"{minutes:.0f} min" if minutes < 120 else f"{minutes / 60:.1f} h"
    text = (f"*Intake daily summary, {day}*\nProcessed: {processed} · Flagged: {flagged} · Approved: {len(rows)}"
            f"\nMedian entry time (upload to approval): {median or 'n/a'}")
    return {"text": text.replace("*", ""), "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]}


def make_notifier(settings) -> Notifier:
    if settings.slack_mode == "webhook":
        return WebhookNotifier(settings.slack_webhook_url)
    return OutboxNotifier(settings.data_dir / "slack_outbox.jsonl")
