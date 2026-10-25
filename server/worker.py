"""Background work: extraction on a small thread pool, and Sheets syncs plus Slack alerts on one worker.

The sync/alert worker is a single asyncio task draining one queue, so there is exactly one writer to the
sheet at a time. server/sheets.py relies on that: its read-column-A-then-append is only safe with one writer.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional, Tuple

from . import forms as R
from .db import Database
from .sheets import SheetsClient, sync_form
from .slack import Notifier, alert_for_form

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, db: Database, extractor: Callable[[Path], dict], sheets: SheetsClient, notifier: Notifier,
                 review_base_url: str):
        self.db, self.extractor, self.sheets, self.notifier = db, extractor, sheets, notifier
        self.review_base_url = review_base_url
        self.queue: "Optional[asyncio.Queue[Tuple[str, int]]]" = None  # made in start(), on the serving loop
        self.extraction_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="extract")
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.task: Optional[asyncio.Task] = None

    # ---- lifecycle ----
    def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self.task = self.loop.create_task(self._run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
        self.extraction_pool.shutdown(wait=False, cancel_futures=True)

    async def drain(self) -> None:
        """Wait until queued syncs and alerts are done (tests and the e2e harness use this)."""
        await self.queue.join()

    # ---- jobs ----
    def enqueue(self, job: str, form_id: int) -> None:
        """Thread-safe: extraction threads call this to queue the alert."""
        if self.loop is None:
            raise RuntimeError("worker not started")
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (job, form_id))

    def extract(self, form_id: int, pdf_path: Path) -> None:
        self.extraction_pool.submit(self.run_extraction, form_id, pdf_path)

    def run_extraction(self, form_id: int, pdf_path: Path) -> None:
        try:
            output = self.extractor(pdf_path)
            R.store_extraction(self.db, form_id, output, pdf_path)
        except Exception as exc:  # noqa: BLE001 - the form must still reach the queue
            log.exception("extraction of form %s failed", form_id)
            R.mark_extraction_failed(self.db, form_id, f"{type(exc).__name__}: {exc}")
            return
        self.enqueue("alert", form_id)

    async def _run(self) -> None:
        while True:
            job, form_id = await self.queue.get()
            try:
                if job == "sync":
                    await asyncio.to_thread(sync_form, self.db, form_id, self.sheets)
                elif job == "alert":
                    await asyncio.to_thread(alert_for_form, self.db, form_id, self.notifier, self.review_base_url)
            except Exception:  # noqa: BLE001 - one bad job must not stop the worker
                log.exception("%s job for form %s failed", job, form_id)
            finally:
                self.queue.task_done()
