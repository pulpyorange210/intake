"""Score a run directory against ground truth.

  python eval.py runs/<timestamp> --dataset synthetic_order_form_dataset_50

Writes eval.json and eval.md into the run directory.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from ofparser.pdf import extract_text

MONEY_FIELDS = ["total_listed_value", "unit_price"]
ITEM_FIELDS = ["currency", "total_listed_value", "quantity", "unit_price", "service_start_date",
               "service_end_date", "invoicing_schedule_type", "invoicing_frequency", "payment_terms",
               "special_notes"]
HEADER_FIELDS = ["effective_date", "contract_signed_date_buying_company", "contract_signed_date_selling_company"]


def norm_text(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower() if s is not None else None


def field_equal(name, pred, gold) -> bool:
    if gold is None or pred is None:
        return gold is None and pred is None
    if name in MONEY_FIELDS:
        return abs(float(pred) - float(gold)) <= 0.01
    if name == "quantity":
        return abs(float(pred) - float(gold)) < 1e-6
    return norm_text(pred) == norm_text(gold)


def read_field(obj: dict, name: str):
    """(value, bucket): bucket is 'unflagged', 'flagged' (value given but marked ambiguous right next to
    it) or 'abstained' (left null because ambiguous)."""
    raw = obj.get(name)
    if isinstance(raw, dict) and "value" in raw:  # invoicing_frequency block
        value, flagged = raw["value"], bool(raw.get("ambiguous"))
    else:
        value, flagged = raw, name in (obj.get("ambiguous_fields") or {})
    if not flagged:
        return value, "unflagged"
    return value, ("abstained" if value is None else "flagged")


BUCKETS = ("unflagged", "flagged", "abstained")


def match_items(pred, gold):
    """Pair items by SKU code; with repeated SKUs, pair by closest total value."""
    pairs, unmatched_pred = [], list(range(len(pred)))
    unmatched_gold = []
    for gi, g in enumerate(gold):
        cands = [pi for pi in unmatched_pred if pred[pi]["sku_code"] == g["sku_code"]]
        if not cands:
            unmatched_gold.append(gi)
            continue
        best = min(cands, key=lambda pi: abs((pred[pi].get("total_listed_value") or 0) - g["total_listed_value"]))
        unmatched_pred.remove(best)
        pairs.append((best, gi))
    return pairs, unmatched_pred, unmatched_gold


def _fold(s: str) -> str:
    """Normalize names/text for mention detection, folding common OCR digit-for-letter swaps."""
    s = s.lower().translate(str.maketrans("150", "lso"))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


def near_twin(text: str, gold_items, catalog) -> bool:
    """Form mentions a catalog product that is NOT sold but whose name overlaps a sold one."""
    folded = _fold(text)
    sold = {_fold(g["sku_name"]) for g in gold_items}
    for entry in catalog:
        name = _fold(entry["name"])
        if name in sold:
            continue
        mentions = folded.count(name) - sum(folded.count(s) for s in sold if name in s and s != name)
        if mentions > 0 and any(name in s or s in name for s in sold):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--dataset", type=Path, default=Path("synthetic_order_form_dataset_50"))
    args = ap.parse_args()

    catalog = json.loads((args.dataset / "sku_catalog.json").read_text())
    stats = defaultdict(lambda: {b: [0, 0] for b in BUCKETS})  # field -> bucket -> [hits, total]
    field_misses = defaultdict(list)
    tp = fp = fn = 0
    twin = Counter()
    perfect_forms, needs_review, freq_source = 0, 0, Counter()
    errors, n_forms, cost = [], 0, 0.0
    item_errors = []

    def score(f, obj, gold_value, label) -> bool:
        value, bucket = read_field(obj, f)
        hit = field_equal(f, value, gold_value)
        stats[f][bucket][0] += hit
        stats[f][bucket][1] += 1
        if not hit:
            tag = {"unflagged": "", "flagged": " [flagged ambiguous]", "abstained": " ABSTAINED"}[bucket]
            field_misses[f].append(f"{label}:{tag} pred={value!r} gold={gold_value!r}")
        return hit

    for out_path in sorted((args.run_dir / "outputs").glob("*.json")):
        form = out_path.stem
        gold = json.loads((args.dataset / "ground_truth" / f"{form}.json").read_text())
        pred = json.loads(out_path.read_text())
        n_forms += 1
        cost += (pred.get("meta") or {}).get("cost_usd") or 0
        needs_review += bool(pred.get("needs_review"))
        p_items, g_items = pred.get("contract_items") or [], gold["contract_items"]
        pairs, up, ug = match_items(p_items, g_items)
        tp += len(pairs); fp += len(up); fn += len(ug)
        for pi in up:
            item_errors.append(f"{form}: extra item {p_items[pi]['sku_code']}")
        for gi in ug:
            item_errors.append(f"{form}: missed item {g_items[gi]['sku_code']}")

        is_twin = near_twin(extract_text(args.dataset / "pdfs" / f"{form}.pdf"), g_items, catalog)
        if is_twin:
            twin["forms"] += 1; twin["tp"] += len(pairs); twin["fp"] += len(up); twin["fn"] += len(ug)

        form_perfect = not up and not ug
        for pi, gi in pairs:
            p, g = p_items[pi], g_items[gi]
            freq = p.get("invoicing_frequency")
            freq_source[freq.get("source") if isinstance(freq, dict) else p.get("invoicing_frequency_source")] += 1
            for f in ITEM_FIELDS:
                form_perfect &= score(f, p, g.get(f), f"{form} {g['sku_code']}")
        header = pred.get("order_form") or {}
        for f in HEADER_FIELDS:
            form_perfect &= score(f, header, gold.get(f), form)
        perfect_forms += form_perfect

    ratio = lambda hits, total: hits / total if total else None
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    twin_p = twin["tp"] / (twin["tp"] + twin["fp"]) if twin["tp"] + twin["fp"] else 0
    twin_r = twin["tp"] / (twin["tp"] + twin["fn"]) if twin["tp"] + twin["fn"] else 0

    result = {
        "forms": n_forms,
        "items": {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1},
        "near_twin_forms": {"forms": twin["forms"], "precision": twin_p, "recall": twin_r},
        "fields": {f: {"overall": ratio(sum(stats[f][b][0] for b in BUCKETS), sum(stats[f][b][1] for b in BUCKETS)),
                       **{b: {"accuracy": ratio(*stats[f][b]), "n": stats[f][b][1]} for b in BUCKETS}}
                   for f in ITEM_FIELDS + HEADER_FIELDS},
        "forms_fully_correct": perfect_forms,
        "needs_review": needs_review,
        "invoicing_frequency_source": dict(freq_source),
        "total_cost_usd": round(cost, 4),
    }
    (args.run_dir / "eval.json").write_text(json.dumps(result, indent=2))

    md = [f"# Eval: {args.run_dir.name}", "",
          f"Forms: {n_forms} | fully correct: {perfect_forms} | needs_review: {needs_review} | cost: ${cost:.2f}", "",
          "## Item detection", "",
          f"Precision {prec:.1%} | Recall {rec:.1%} | F1 {f1:.1%} (TP {tp}, FP {fp}, FN {fn})", "",
          f"Near-twin forms (a non-sold catalog name overlaps a sold one): {twin['forms']} forms, "
          f"precision {twin_p:.1%}, recall {twin_r:.1%}", "",
          "## Field accuracy", "",
          "Overall counts every matched item (abstentions count as wrong). The other columns split it by how "
          "the output was marked: unflagged answers, answers flagged ambiguous (value given with the ambiguity "
          "next to it), and abstentions (left null because ambiguous).", ""]
    fmt = lambda b: "-" if not b["n"] else f"{b['accuracy']:.1%} (n={b['n']})"
    for title, fields in (("Contract items", ITEM_FIELDS), ("Order form header", HEADER_FIELDS)):
        md += [f"### {title}", "", "| Field | Overall | Unflagged | Flagged ambiguous | Abstained |",
               "|---|---|---|---|---|"]
        for f in fields:
            r = result["fields"][f]
            md.append(f"| {f} | {r['overall']:.1%} | {fmt(r['unflagged'])} | {fmt(r['flagged'])} | "
                      f"{r['abstained']['n'] or '-'} |")
        md.append("")
    md += [f"invoicing_frequency source: {dict(freq_source)}", "", "## Failures", ""]
    if item_errors:
        md += ["### Item detection"] + [f"- {e}" for e in item_errors] + [""]
    for f in ITEM_FIELDS + HEADER_FIELDS:
        if field_misses[f]:
            md += [f"### {f} ({len(field_misses[f])})"] + [f"- {m}" for m in field_misses[f]] + [""]
    (args.run_dir / "eval.md").write_text("\n".join(md))
    print("\n".join(md[:30]))


if __name__ == "__main__":
    main()
