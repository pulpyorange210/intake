"""Settings, from environment variables only (see .env.example). Nothing here is required: without the
Google or Slack variables the app writes to a local CSV "sheet" and a local alert outbox instead."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=value lines); real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    data_dir: Path
    db_path: Path
    catalog_path: Path
    extractor: str                       # "live" (Claude API) or "replay" (recorded responses)
    cassettes_dir: Path
    google_service_account_json: Optional[str]
    sheet_id: Optional[str]
    slack_webhook_url: Optional[str]
    review_ui_base_url: str

    @property
    def sheets_mode(self) -> str:
        return "google" if self.google_service_account_json and self.sheet_id else "csv"

    @property
    def slack_mode(self) -> str:
        return "webhook" if self.slack_webhook_url else "outbox"

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(ROOT / ".env")
        data_dir = Path(os.environ.get("INTAKE_DATA_DIR", ROOT / "data"))
        extractor = os.environ.get("INTAKE_EXTRACTOR") or ("live" if os.environ.get("ANTHROPIC_API_KEY") else "replay")
        return cls(
            data_dir=data_dir,
            db_path=Path(os.environ.get("INTAKE_DB", data_dir / "intake.db")),
            catalog_path=Path(os.environ.get("INTAKE_CATALOG", ROOT / "synthetic_order_form_dataset_50" / "sku_catalog.json")),
            extractor=extractor,
            cassettes_dir=Path(os.environ.get("INTAKE_CASSETTES", ROOT / "evals" / "cassettes")),
            google_service_account_json=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or None,
            sheet_id=os.environ.get("SHEET_ID") or None,
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL") or None,
            review_ui_base_url=os.environ.get("REVIEW_UI_BASE_URL", "http://localhost:5173").rstrip("/"),
        )
