"""Review API (FastAPI).

  uvicorn server.app:app --reload        # or: make dev
"""
from __future__ import annotations

import hashlib
import logging
import statistics
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Dict, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ofparser.catalog import Catalog

from . import forms as R
from .config import Settings
from .db import Database
from .extractors import live_extractor, replay_extractor
from .sheets import make_client
from .slack import make_notifier
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class ReviewAction(BaseModel):
    action: str                      # "accept" | "edit"
    values: Optional[Dict[str, object]] = None


def create_app(settings: Optional[Settings] = None, extractor: Optional[Callable[[Path], dict]] = None,
               sheets=None, notifier=None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    catalog = Catalog.load(settings.catalog_path)
    if extractor is None:
        extractor = (live_extractor(catalog) if settings.extractor == "live"
                     else replay_extractor(catalog, settings.cassettes_dir))
    worker = Worker(db, extractor, sheets or make_client(settings), notifier or make_notifier(settings),
                    settings.review_ui_base_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker.start()
        logging.getLogger(__name__).info("extractor=%s sheets=%s slack=%s db=%s", settings.extractor,
                                         settings.sheets_mode, settings.slack_mode, settings.db_path)
        yield
        await worker.stop()

    app = FastAPI(title="Intake review API", lifespan=lifespan)
    app.state.settings, app.state.db, app.state.worker = settings, db, worker
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(R.ReviewError)
    async def review_error(_request, exc: R.ReviewError):
        return JSONResponse(status_code=422, content={"detail": str(exc), "fields": exc.fields})

    def found(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except KeyError:
            raise HTTPException(404, "not found") from None

    @app.get("/health")
    def health():
        return {"ok": True, "extractor": settings.extractor, "sheets": settings.sheets_mode,
                "slack": settings.slack_mode}

    @app.post("/forms", status_code=201)
    async def upload(file: UploadFile = File(...), wait: bool = Query(False)):
        """Store the PDF and start extraction plus the checker. Returns at once with status 'processing'
        (poll GET /forms/{id}); with ?wait=true it returns after extraction finishes."""
        data = await file.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(422, "not a PDF")
        content_hash = hashlib.sha256(data).hexdigest()
        pdf_dir = settings.data_dir / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"{content_hash}.pdf"
        pdf_path.write_bytes(data)
        form_id = R.create_form(db, Path(file.filename or "upload.pdf").name, pdf_path, content_hash)
        if wait:
            import asyncio
            await asyncio.to_thread(worker.run_extraction, form_id, pdf_path)
        else:
            worker.extract(form_id, pdf_path)
        return {"form_id": form_id, "status": R.get_form(db, form_id)["status"]}

    @app.post("/forms/{form_id}/extract")
    def reextract(form_id: int):
        """Re-run extraction (replaces the review rows; an alert already sent is not sent again)."""
        form = found(R.get_form, db, form_id)
        if form["status"] == "approved":
            raise HTTPException(409, "form is approved")
        with db.connect() as conn:
            pdf_path = Path(conn.execute("SELECT pdf_path FROM forms WHERE id = ?", (form_id,)).fetchone()[0])
        worker.extract(form_id, pdf_path)
        return {"form_id": form_id}

    @app.get("/forms")
    def queue(status: Optional[str] = Query(None, pattern="^(processing|needs_review|approved|rejected|sync_failed)$")):
        return R.list_forms(db, status)

    @app.get("/forms/{form_id}")
    def form(form_id: int, review: bool = Query(False)):
        return found(R.get_form, db, form_id, opened_for_review=review)

    @app.patch("/forms/{form_id}/items/{item_id}")
    def review_item(form_id: int, item_id: int, body: ReviewAction):
        return found(R.review_item, db, catalog, form_id, item_id, body.action, body.values)

    @app.patch("/forms/{form_id}/header")
    def review_header(form_id: int, body: ReviewAction):
        return found(R.review_header, db, form_id, body.action, body.values)

    @app.post("/forms/{form_id}/accept-minor")
    def accept_minor(form_id: int):
        return found(R.accept_all_minor, db, form_id)

    @app.post("/forms/{form_id}/approve")
    def approve(form_id: int):
        """Allowed only when every high flag is accepted or edited. Triggers the Sheets sync; approving again
        re-runs the sync, which adds nothing that is already in the sheet."""
        try:
            result, _ = found(R.approve, db, form_id)
        except R.ReviewError as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc), "fields": exc.fields})
        worker.enqueue("sync", form_id)
        return result

    @app.post("/forms/{form_id}/reject")
    def reject(form_id: int):
        return found(R.reject, db, form_id)

    @app.post("/forms/{form_id}/sync")
    def retry_sync(form_id: int):
        """Manual retry for a form whose sync failed."""
        if found(R.get_form, db, form_id)["status"] != "approved":
            raise HTTPException(409, "only approved forms are synced")
        worker.enqueue("sync", form_id)
        return {"form_id": form_id, "queued": True}

    @app.get("/forms/{form_id}/pdf")
    def pdf(form_id: int):
        with db.connect() as conn:
            row = conn.execute("SELECT pdf_path, filename FROM forms WHERE id = ?", (form_id,)).fetchone()
        if row is None or not Path(row["pdf_path"]).exists():
            raise HTTPException(404, "not found")
        return FileResponse(row["pdf_path"], media_type="application/pdf", filename=row["filename"],
                            content_disposition_type="inline")

    @app.get("/catalog")
    def catalog_list():
        return [{"sku": e["sku_code"], "name": e.get("name")} for e in catalog.entries]

    @app.get("/metrics")
    def metrics():
        forms = R.list_forms(db)
        times = R.entry_times(db)
        by_status: Dict[str, int] = {}
        for f in forms:
            by_status[f["status"]] = by_status.get(f["status"], 0) + 1
        return {"forms": len(forms), "by_status": by_status,
                "flagged": sum(1 for f in forms if f["top_severity"]),
                "median_entry_seconds": statistics.median(times) if times else None}

    return app


def __getattr__(name: str):
    """`uvicorn server.app:app` builds the app on first access, so importing this module has no side effects."""
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
