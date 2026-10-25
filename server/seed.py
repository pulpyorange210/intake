"""Load recorded forms into the review database for a demo, with no API key.

  python -m server.seed            # 12 forms: the flagged ones first, then some clean ones
  python -m server.seed --all      # all 50 synthetic forms
"""
from __future__ import annotations

import argparse
import hashlib
import shutil

from ofparser.catalog import Catalog

from . import forms as R
from .config import ROOT, Settings
from .db import Database
from .extractors import replay_extractor
from .flags import derive_flags

PDFS = ROOT / "synthetic_order_form_dataset_50" / "pdfs"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-n", type=int, default=12)
    args = ap.parse_args()
    settings = Settings.from_env()
    db = Database(settings.db_path)
    extract = replay_extractor(Catalog.load(settings.catalog_path), settings.cassettes_dir)
    outputs = {pdf: extract(pdf) for pdf in sorted(PDFS.glob("*.pdf"))}
    order = sorted(outputs, key=lambda pdf: not derive_flags(outputs[pdf]))  # flagged first, stable by name
    chosen = order if args.all else order[: args.n]
    (settings.data_dir / "pdfs").mkdir(parents=True, exist_ok=True)
    for pdf in chosen:
        data = pdf.read_bytes()
        content_hash = hashlib.sha256(data).hexdigest()
        stored = settings.data_dir / "pdfs" / f"{content_hash}.pdf"
        shutil.copyfile(pdf, stored)
        form_id = R.create_form(db, pdf.name, stored, content_hash)
        R.store_extraction(db, form_id, outputs[pdf], stored)
    print(f"seeded {len(chosen)} forms into {settings.db_path}")


if __name__ == "__main__":
    main()
