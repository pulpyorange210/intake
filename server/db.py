"""SQLite system of record for review state (one file, intake.db)."""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS forms (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,              -- sha256 of the PDF bytes; part of every sync idempotency key
    uploaded_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'needs_review', 'approved', 'rejected')),
    approved_at TEXT,
    extraction_json TEXT,                    -- the parser's full output, unchanged
    extraction_error TEXT,
    header_json TEXT,                        -- order-form fields shown for review (effective date, totals, ...)
    header_reviewer_action TEXT CHECK (header_reviewer_action IN ('accepted', 'edited')),
    header_edited_values_json TEXT
);
CREATE TABLE IF NOT EXISTS line_items (
    id INTEGER PRIMARY KEY,
    form_id INTEGER NOT NULL REFERENCES forms(id),
    line_index INTEGER NOT NULL,
    sku TEXT, description TEXT, qty REAL, unit_price REAL, amount REAL,
    service_start TEXT, service_end TEXT, billing_terms TEXT,
    currency TEXT, payment_terms TEXT,
    flag_severity TEXT CHECK (flag_severity IN ('low', 'medium', 'high')),   -- highest of the item's flags
    flag_reason TEXT,
    source_page INTEGER,                     -- page of the priced row the item was read from
    source_text TEXT,
    evidence_json TEXT,                      -- per field: {"quote", "page"} for click-to-highlight
    reviewer_action TEXT CHECK (reviewer_action IN ('accepted', 'edited')),
    edited_values_json TEXT,
    UNIQUE (form_id, line_index)
);
CREATE TABLE IF NOT EXISTS flags (
    id INTEGER PRIMARY KEY,
    form_id INTEGER NOT NULL REFERENCES forms(id),
    line_index INTEGER,                      -- NULL: an order-form (header) field
    field TEXT,
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    "check" TEXT NOT NULL,                   -- the checker's name for it (missing_value, sku_ambiguous, ...)
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_log (
    idempotency_key TEXT PRIMARY KEY,
    form_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    form_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('uploaded', 'extracted', 'review_opened', 'approved', 'synced', 'alert_sent')),
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_form ON events (form_id, type);
CREATE INDEX IF NOT EXISTS sync_form ON sync_log (form_id);
"""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Database:
    """Opens a short-lived connection per unit of work; the extraction threads and the sync/alert worker each
    get their own, and SQLite's busy timeout serialises their writes."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise


def log_event(conn: sqlite3.Connection, form_id: int, type_: str, at: Optional[str] = None) -> None:
    conn.execute("INSERT INTO events (form_id, type, at) VALUES (?, ?, ?)", (form_id, type_, at or now()))


def has_event(conn: sqlite3.Connection, form_id: int, type_: str) -> bool:
    return conn.execute("SELECT 1 FROM events WHERE form_id = ? AND type = ? LIMIT 1", (form_id, type_)).fetchone() is not None
