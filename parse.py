"""Parse order form PDFs against a SKU catalog.

Examples:
  python parse.py --catalog synthetic_order_form_dataset_50/sku_catalog.json path/to/form.pdf
  python parse.py --catalog synthetic_order_form_dataset_50/sku_catalog.json synthetic_order_form_dataset_50/pdfs/*.pdf
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

from ofparser.agent import CATALOG_MODES, DEFAULT_MODEL, LONG_DOC_MODES, parse_order_form
from ofparser.catalog import Catalog


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--out", type=Path, help="run directory (default: runs/<timestamp>)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--long-doc", default="outline", choices=LONG_DOC_MODES,
                    help="how documents over 30 pages are shown: a code-built outline the model navigates "
                         "(default), or the highest-scoring pages sent up front")
    ap.add_argument("--catalog-mode", default="auto", choices=CATALOG_MODES,
                    help="auto: catalogs up to 200 SKUs go in the prompt, larger ones are searched with the "
                         "search_catalog tool; inline / retrieval force one or the other")
    args = ap.parse_args()

    run_dir = args.out or Path("runs") / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    (run_dir / "outputs").mkdir(parents=True, exist_ok=True)
    catalog = Catalog.load(args.catalog)
    client = anthropic.Anthropic()

    def work(pdf: Path):
        out = parse_order_form(pdf, catalog, client, model=args.model, effort=args.effort,
                               transcript_path=run_dir / "transcripts" / f"{pdf.stem}.json",
                               long_doc=args.long_doc, catalog_mode=args.catalog_mode)
        (run_dir / "outputs" / f"{pdf.stem}.json").write_text(json.dumps(out, indent=2))
        return pdf, out

    total_cost, failures = 0.0, []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, pdf): pdf for pdf in args.pdfs}
        for fut in as_completed(futures):
            pdf = futures[fut]
            try:
                _, out = fut.result()
            except Exception as exc:  # keep the batch going; record the failure
                failures.append({"pdf": pdf.name, "error": repr(exc)})
                print(f"FAIL {pdf.name}: {exc!r}", file=sys.stderr)
                continue
            meta = out["meta"]
            total_cost += meta["cost_usd"] or 0
            flag = " NEEDS_REVIEW" if out["needs_review"] else ""
            print(f"{pdf.name}: {out['contract_items_count']} items, {meta['submissions']} submission(s), "
                  f"{meta['seconds']}s, ${meta['cost_usd']}{flag}")

    (run_dir / "run_meta.json").write_text(json.dumps({
        "model": args.model, "effort": args.effort, "catalog": str(args.catalog), "long_doc": args.long_doc,
        "catalog_mode": args.catalog_mode,
        "n_pdfs": len(args.pdfs), "failures": failures, "total_cost_usd": round(total_cost, 4),
    }, indent=2))
    print(f"\nRun dir: {run_dir}  |  total cost ${total_cost:.2f}  |  failures: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
