"""Report for catalog-scaling runs: retrieval recall, item accuracy, input tokens and cost, with the v0.8 run
(21-SKU catalog) on the same forms as the baseline.

Retrieval recall: for each expected contract item, whether its SKU was among the candidates any search_catalog
call returned on that form (top matches plus siblings). Only meaningful for retrieval-mode runs.

  python scripts/catalog_report.py runs/catalog2000_inline runs/catalog2000_retrieval --baseline runs/v0.8
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import score_run  # noqa: E402
from ofparser.postprocess import sku_value  # noqa: E402

DATASET = ROOT / "synthetic_order_form_dataset_50"
FIELDS = ["total_listed_value", "quantity", "unit_price", "service_start_date", "service_end_date", "payment_terms"]


def run_stats(run_dir: Path, forms=None) -> dict:
    outputs = sorted((run_dir / "outputs").glob("*.json"))
    if forms is not None:
        outputs = [p for p in outputs if p.stem in forms]
    tokens = cost = 0.0
    searches = recall_hit = recall_n = 0
    wrong = []
    mode = None
    for p in outputs:
        out = json.loads(p.read_text())
        meta = out["meta"]
        u = meta["usage"]
        tokens += u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"]
        cost += meta["cost_usd"] or 0
        cat = meta.get("catalog") or {}
        mode = cat.get("mode", "inline (21 SKUs)")
        gold = [i["sku_code"] for i in json.loads((DATASET / "ground_truth" / f"{p.stem}.json").read_text())
                ["contract_items"]]
        cands = {c for s in cat.get("searches", []) for c in s["candidates"]}
        searches += len(cat.get("searches", []))
        if cat.get("mode") == "retrieval":
            recall_n += len(gold)
            recall_hit += sum(g in cands for g in gold)
        pred = [sku_value(i["sku_code"]) for i in out.get("contract_items") or []]
        extra, missed = sorted(set(pred) - set(gold)), sorted(set(gold) - set(pred))
        if extra or missed:
            wrong.append(f"{p.stem}: chose {extra or '-'} where expected {missed or '-'}")
    return {"forms": len(outputs), "tokens": tokens, "cost": cost, "searches": searches,
            "recall": (recall_hit, recall_n), "wrong": wrong, "mode": mode}


def subset_dir(run_dir: Path, forms) -> Path:
    """score_run reads run_dir/outputs; build a temporary view with only the given forms."""
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "run"
    (tmp / "outputs").mkdir(parents=True)
    for f in forms:
        (tmp / "outputs" / f"{f}.json").write_text((run_dir / "outputs" / f"{f}.json").read_text())
    return tmp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--baseline", type=Path, default=ROOT / "runs" / "v0.8")
    args = ap.parse_args()

    print("| Run | Catalog | Forms | Item precision / recall | Retrieval recall | Fields correct | "
          "Input tokens / form | Cost / form | Wrong SKU |")
    print("|---|---|---|---|---|---|---|---|---|")
    notes = []
    for run in args.runs:
        forms = [p.stem for p in sorted((run / "outputs").glob("*.json"))]
        for label, run_dir in ((f"baseline ({args.baseline.name}, same forms)", args.baseline), (run.name, run)):
            res, _ = score_run(subset_dir(run_dir, forms), DATASET)
            st = run_stats(run_dir, set(forms))
            it = res["items"]
            fields = res["fields"]
            n_each = {f: sum(fields[f][b]["n"] for b in ("unflagged", "flagged", "abstained")) for f in FIELDS}
            hit = sum(round((fields[f]["overall"] or 0) * n_each[f]) for f in FIELDS)
            n = sum(n_each.values())
            rh, rn = st["recall"]
            print(f"| {label} | {st['mode']} | {st['forms']} | {it['precision']:.1%} / {it['recall']:.1%} | "
                  f"{f'{rh}/{rn}' if rn else '-'} | {hit}/{n} | {st['tokens'] / st['forms']:,.0f} | "
                  f"${st['cost'] / st['forms']:.3f} | {len(st['wrong'])} |")
            if run_dir == run:
                notes.append((run.name, st))
    for name, st in notes:
        print(f"\n### {name}")
        print(f"- total cost ${st['cost']:.2f}; catalog searches {st['searches']}")
        print("- wrong SKUs: " + ("; ".join(st["wrong"]) if st["wrong"] else "none"))


if __name__ == "__main__":
    main()
