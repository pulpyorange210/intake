"""Report for the long-document variants: pages seen, page recall, tokens, cost, time, and whether the expected
contract items came out correct.

Page recall: of the pages that hold information the order needs (listed per variant in variants.json), how
many the model actually saw, either sent up front or fetched with read_pages. Search results don't count:
they show matching lines, not pages.

  python scripts/long_doc_report.py runs/long_doc
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ofparser.postprocess import sku_value  # noqa: E402
CASE_DIR = ROOT / "edge_cases" / "long_document"
VARIANTS = CASE_DIR / "variants.json"


def expected_for(info: dict) -> dict:
    name = info.get("expected", "expected.json")
    path = CASE_DIR / name if (CASE_DIR / name).exists() else ROOT / "edge_cases" / "example_order_form_redacted" / name
    return json.loads(path.read_text())


def pages_seen(long_doc: dict) -> set:
    if "pages_seen" in long_doc:
        return set(long_doc["pages_seen"])
    return set(map(int, long_doc.get("pages_sent") or {})) | set(long_doc.get("pages_read", []))  # v0.9 runs

# Fields that decide "correct"; payment_terms and special_notes are reported separately (known wording
# differences on the 5-page form itself).
CHECKED = ["currency", "total_listed_value", "quantity", "unit_price", "service_start_date", "service_end_date",
           "invoicing_schedule_type", "invoicing_frequency"]


def compare(output: dict, expected: dict):
    pred = {sku_value(i["sku_code"]): i for i in output.get("contract_items", [])}
    gold = {i["sku_reference"]: i for i in expected["contract_items"]}
    problems = [f"extra {c}" for c in sorted(set(pred) - set(gold))]
    problems += [f"missing {c}" for c in sorted(set(gold) - set(pred))]
    for code in sorted(set(pred) & set(gold)):
        p, g = pred[code], gold[code]
        for f in CHECKED:
            pv = p[f]["value"] if f == "invoicing_frequency" and isinstance(p[f], dict) else p[f]
            gv = g[f]
            same = (round(float(pv), 2) == round(float(gv), 2)) if isinstance(gv, (int, float)) and pv is not None \
                else pv == gv
            if not same:
                problems.append(f"{code}.{f}: {pv!r} != {gv!r}")
    return not problems, problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    args = ap.parse_args()
    variants = json.loads(VARIANTS.read_text())

    print("| Variant | Mode | Pages seen | Page recall | Searches | Input tokens | Output tokens | Cost | Time | "
          "Turns | Items correct |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    details = []
    for name, info in variants.items():
        path = args.run_dir / "outputs" / f"{name}.json"
        if not path.exists():
            continue
        out = json.loads(path.read_text())
        meta = out["meta"]
        long_doc = meta.get("long_document") or {}
        u = meta["usage"]
        tokens_in = u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"]
        ok, problems = compare(out, expected_for(info))
        needed = {int(p) for p in info["needed_pages"]}
        seen = pages_seen(long_doc)
        missed = sorted(needed - seen)
        recall = f"{len(needed & seen)}/{len(needed)}" + (f" (missed {', '.join(map(str, missed))})" if missed else "")
        print(f"| {name} | {long_doc.get('mode', 'select')} | {len(seen)} | {recall} | {long_doc.get('searches', 0)} | "
              f"{tokens_in:,} | {u['output_tokens']:,} | ${meta['cost_usd']:.2f} | {meta['seconds']:.0f}s | "
              f"{meta['turns']} | {'yes' if ok else 'NO'} |")
        details.append((name, out, problems, long_doc, info, seen))

    for name, out, problems, long_doc, info, seen in details:
        print(f"\n### {name}")
        print(f"- needed: " + "; ".join(f"p.{p} {what}" for p, what in info["needed_pages"].items()))
        if long_doc.get("pages_sent"):
            print(f"- pages sent up front: {', '.join(map(str, long_doc['pages_sent']))}")
        print(f"- pages read: {', '.join(map(str, long_doc.get('pages_read', []))) or 'none'}")
        print(f"- items: {[sku_value(i['sku_code']) for i in out['contract_items']]}; "
              f"excluded: {out.get('explicitly_excluded_skus')}")
        print(f"- needs_review: {out['needs_review']}; problems: {problems or 'none'}")
        terms = {sku_value(i["sku_code"]): (i["payment_terms"], i["special_notes"]) for i in out["contract_items"]}
        print(f"- payment terms / special notes: {terms}")
        h = out["order_form"] or {}
        print(f"- header: effective {h.get('effective_date')}, signed buyer "
              f"{h.get('contract_signed_date_buying_company')}, seller {h.get('contract_signed_date_selling_company')}, "
              f"grand total {h.get('grand_total')}")


if __name__ == "__main__":
    main()
