"""Google Sheets sync: every approved form's line items land in the sheet exactly once.

One row per line item, keyed by an idempotency key in column A. The sync re-reads column A before every
append and only appends keys that aren't there yet, so a retry after "the append succeeded but the response
never arrived" (or after a crash before the result was recorded) doesn't duplicate rows.

ASSUMPTION: a single writer. Syncs run through one background worker (server/worker.py), so nothing can
append between this process reading column A and appending. Running several workers or app processes against
the same sheet would make that check-then-append racy and could duplicate rows.
"""
from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Protocol, Set

import httpx

from . import retry
from .db import Database, log_event, now
from .forms import effective_item
from .idempotency import line_key

log = logging.getLogger(__name__)

COLUMNS = ["idempotency_key", "form_id", "filename", "line_index", "sku", "description", "qty", "unit_price",
           "amount", "service_start", "service_end", "billing_terms", "approved_at", "reviewer_edited"]
KEY_FIELDS = ("sku", "description", "qty", "unit_price", "amount", "service_start", "service_end", "billing_terms")


class SheetsClient(Protocol):
    def read_keys(self) -> Set[str]:
        """Every value in column A."""

    def append(self, rows: List[list]) -> None:
        """Append rows in one call."""


class GoogleSheetsClient:
    """Sheets API v4 over HTTPS with a service account (GOOGLE_SERVICE_ACCOUNT_JSON: the key file's JSON, or a
    path to it). Share the sheet with the service account's email as an editor."""

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    BASE = "https://sheets.googleapis.com/v4/spreadsheets"

    def __init__(self, service_account_json: str, sheet_id: str, tab: str = "Sheet1", timeout: float = 30):
        from google.oauth2 import service_account
        info = json.loads(Path(service_account_json).read_text() if not service_account_json.lstrip().startswith("{")
                          else service_account_json)
        self.credentials = service_account.Credentials.from_service_account_info(info, scopes=self.SCOPES)
        self.sheet_id, self.tab = sheet_id, tab
        self.http = httpx.Client(timeout=timeout)

    def _headers(self) -> dict:
        if not self.credentials.valid:
            from google.auth.transport.requests import Request
            self.credentials.refresh(Request())
        return {"Authorization": f"Bearer {self.credentials.token}"}

    @staticmethod
    def _check(response: httpx.Response) -> dict:
        if response.status_code >= 400:
            raise retry.HTTPStatusError(response.status_code, response.text)
        return response.json()

    def read_keys(self) -> Set[str]:
        data = self._check(self.http.get(f"{self.BASE}/{self.sheet_id}/values/{self.tab}!A:A",
                                         headers=self._headers()))
        return {row[0] for row in data.get("values", []) if row}

    def append(self, rows: List[list]) -> None:
        self._check(self.http.post(
            f"{self.BASE}/{self.sheet_id}/values/{self.tab}!A:A:append",
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            headers=self._headers(), json={"values": rows}))


class CsvSheet:
    """Local stand-in for the sheet when no Google credentials are configured: same interface, a CSV file."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read_keys(self) -> Set[str]:
        if not self.path.exists():
            return set()
        with self.path.open(newline="") as f:
            return {row[0] for row in csv.reader(f) if row and row[0] != COLUMNS[0]}

    def append(self, rows: List[list]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with self.path.open("a", newline="") as f:
            writer = csv.writer(f)
            if new:
                writer.writerow(COLUMNS)
            writer.writerows(rows)


def form_rows(conn, form_id: int) -> List[tuple]:
    """(key, row) for each line item of an approved form, from its reviewed values."""
    form = conn.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
    out = []
    for item in conn.execute("SELECT * FROM line_items WHERE form_id = ? ORDER BY line_index", (form_id,)):
        values = effective_item(item)
        final = {f: values[f] for f in KEY_FIELDS}
        key = line_key(form["content_hash"], item["line_index"], final)
        row = [key, form_id, form["filename"], item["line_index"], *(final[f] for f in KEY_FIELDS),
               form["approved_at"], "TRUE" if item["reviewer_action"] == "edited" else "FALSE"]
        out.append((key, ["" if v is None else v for v in row]))
    return out


def _set_status(conn, keys: Iterable[str], status: str, error: Optional[str] = None) -> None:
    for key in keys:
        conn.execute("UPDATE sync_log SET status = ?, last_error = ?, updated_at = ? WHERE idempotency_key = ?",
                     (status, error, now(), key))


def sync_form(db: Database, form_id: int, client: SheetsClient, sleep: Callable[[float], None] = time.sleep,
              max_attempts: int = retry.MAX_ATTEMPTS) -> str:
    """Sync one approved form. Returns the outcome: 'done', 'failed' or 'nothing_to_do'."""
    with db.transaction() as conn:
        form = conn.execute("SELECT status FROM forms WHERE id = ?", (form_id,)).fetchone()
        if form is None or form["status"] != "approved":
            return "nothing_to_do"
        rows = form_rows(conn, form_id)
        for key, _ in rows:  # 1. record every key as pending (a key synced before stays done)
            conn.execute("INSERT OR IGNORE INTO sync_log (idempotency_key, form_id, status, attempts, updated_at) "
                         "VALUES (?, ?, 'pending', 0, ?)", (key, form_id, now()))
        conn.execute("UPDATE sync_log SET status = 'pending' WHERE form_id = ? AND status = 'failed'", (form_id,))
        pending = {r["idempotency_key"] for r in conn.execute(
            "SELECT idempotency_key FROM sync_log WHERE form_id = ? AND status = 'pending'", (form_id,))}
    pending_rows = [(k, row) for k, row in rows if k in pending]
    if not pending_rows:
        return "done"

    for attempt in range(1, max_attempts + 1):
        with db.transaction() as conn:
            conn.executemany("UPDATE sync_log SET attempts = attempts + 1, updated_at = ? WHERE idempotency_key = ?",
                             [(now(), k) for k, _ in pending_rows])
        try:
            in_sheet = client.read_keys()                                      # 2. read column A once
            to_append = [(k, row) for k, row in pending_rows if k not in in_sheet]  # 3. only what's missing
            if to_append:
                client.append([row for _, row in to_append])
        except Exception as exc:  # noqa: BLE001 - classified below; anything unexpected is a permanent failure
            error = f"{type(exc).__name__}: {exc}"[:500]
            if retry.is_retryable(exc) and attempt < max_attempts:
                log.warning("sheets sync of form %s, attempt %s failed (%s); retrying", form_id, attempt, error)
                with db.transaction() as conn:
                    conn.executemany("UPDATE sync_log SET last_error = ? WHERE idempotency_key = ?",
                                     [(error, k) for k, _ in pending_rows])
                sleep(retry.backoff(attempt))
                continue  # 5. re-run from the read: the failed attempt may have landed
            log.error("sheets sync of form %s failed: %s", form_id, error)
            with db.transaction() as conn:
                _set_status(conn, (k for k, _ in pending_rows), "failed", error)
            return "failed"
        with db.transaction() as conn:
            # 4. appended keys are done, and so are keys already in the sheet (an earlier append that landed
            # before a crash or a lost response).
            _set_status(conn, (k for k, _ in pending_rows), "done")
            log_event(conn, form_id, "synced")
        return "done"
    return "failed"


def make_client(settings) -> SheetsClient:
    if settings.sheets_mode == "google":
        return GoogleSheetsClient(settings.google_service_account_json, settings.sheet_id)
    return CsvSheet(settings.data_dir / "sheet.csv")
