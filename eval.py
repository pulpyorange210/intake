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

from ofparser.pdf import cents, extract_text
from ofparser.postprocess import sku_value

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
        return cents(pred) == cents(gold)  # exact to the cent
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


def sku_flagged(item) -> bool:
    sku = item.get("sku_code")
    return isinstance(sku, dict) and bool(sku.get("ambiguous"))


def sku_candidates(item) -> set:
    sku = item.get("sku_code")
    return {sku_value(sku)} | set(sku.get("alternatives") or []) if isinstance(sku, dict) else {sku}


def match_items(pred, gold):
    """Pair items by SKU code; with repeated SKUs, pair by closest total value.

    An unflagged prediction pairs on its SKU. A prediction whose SKU is flagged ambiguous pairs with an expected
    item whose SKU is among its candidates (value or alternatives); such pairs are returned separately, so they
    count as neither correct nor wrong. A flagged SKU whose candidates don't include the expected one is an error.
    Returns (pairs, flagged_pairs, unmatched_pred, unmatched_gold).
    """
    pairs, flagged_pairs, unmatched_pred = [], [], list(range(len(pred)))
    unmatched_gold = []

    def closest(cands, g):
        return min(cands, key=lambda pi: abs((pred[pi].get("total_listed_value") or 0) - g["total_listed_value"]))

    for gi, g in enumerate(gold):
        cands = [pi for pi in unmatched_pred
                 if not sku_flagged(pred[pi]) and sku_value(pred[pi]["sku_code"]) == g["sku_code"]]
        if cands:
            best = closest(cands, g)
            unmatched_pred.remove(best)
            pairs.append((best, gi))
            continue
        cands = [pi for pi in unmatched_pred if sku_flagged(pred[pi]) and g["sku_code"] in sku_candidates(pred[pi])]
        if cands:
            best = closest(cands, g)
            unmatched_pred.remove(best)
            flagged_pairs.append((best, gi))
            continue
        unmatched_gold.append(gi)
    return pairs, flagged_pairs, unmatched_pred, unmatched_gold


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


def score_run(run_dir: Path, dataset: Path):
    """Score run_dir/outputs/*.json against dataset/ground_truth. Returns (result dict, markdown lines)."""
    catalog = json.loads((dataset / "sku_catalog.json").read_text())
    stats = defaultdict(lambda: {b: [0, 0] for b in BUCKETS})  # field -> bucket -> [hits, total]
    field_misses = defaultdict(list)
    tp = fp = fn = 0
    twin = Counter()
    perfect_forms, needs_review, freq_source = 0, 0, Counter()
    errors, n_forms, cost = [], 0, 0.0
    flagged = Counter()  # SKUs flagged ambiguous with the expected SKU among the candidates
    item_errors, flagged_items = [], []

    def score(f, obj, gold_value, label) -> bool:
        value, bucket = read_field(obj, f)
        hit = field_equal(f, value, gold_value)
        stats[f][bucket][0] += hit
        stats[f][bucket][1] += 1
        if not hit:
            tag = {"unflagged": "", "flagged": " [flagged ambiguous]", "abstained": " ABSTAINED"}[bucket]
            field_misses[f].append(f"{label}:{tag} pred={value!r} gold={gold_value!r}")
        return hit

    for out_path in sorted((run_dir / "outputs").glob("*.json")):
        form = out_path.stem
        gold = json.loads((dataset / "ground_truth" / f"{form}.json").read_text())
        pred = json.loads(out_path.read_text())
        n_forms += 1
        cost += (pred.get("meta") or {}).get("cost_usd") or 0
        needs_review += bool(pred.get("needs_review"))
        p_items, g_items = pred.get("contract_items") or [], gold["contract_items"]
        pairs, fpairs, up, ug = match_items(p_items, g_items)
        tp += len(pairs); fp += len(up); fn += len(ug)
        for pi, gi in fpairs:
            expected_is_value = sku_value(p_items[pi]["sku_code"]) == g_items[gi]["sku_code"]
            flagged["n"] += 1
            flagged["value" if expected_is_value else "alternative"] += 1
            flagged_items.append(f"{form}: {sku_value(p_items[pi]['sku_code'])} flagged, alternatives "
                                 f"{p_items[pi]['sku_code'].get('alternatives')}, expected {g_items[gi]['sku_code']}")
        for pi in up:
            item_errors.append(f"{form}: extra item {sku_value(p_items[pi]['sku_code'])}")
        for gi in ug:
            item_errors.append(f"{form}: missed item {g_items[gi]['sku_code']}")

        is_twin = near_twin(extract_text(dataset / "pdfs" / f"{form}.pdf"), g_items, catalog)
        if is_twin:
            twin["forms"] += 1; twin["tp"] += len(pairs); twin["fp"] += len(up); twin["fn"] += len(ug)
            twin["flagged"] += len(fpairs)

        form_perfect = not up and not ug and not fpairs
        for pi, gi in pairs + fpairs:  # a flagged SKU's other fields still describe the same line
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
        "items": {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1,
                  "flagged": {"n": flagged["n"], "expected_is_value": flagged["value"],
                              "expected_in_alternatives": flagged["alternative"]}},
        "near_twin_forms": {"forms": twin["forms"], "precision": twin_p, "recall": twin_r,
                            "flagged": twin["flagged"]},
        "fields": {f: {"overall": ratio(sum(stats[f][b][0] for b in BUCKETS), sum(stats[f][b][1] for b in BUCKETS)),
                       **{b: {"accuracy": ratio(*stats[f][b]), "n": stats[f][b][1]} for b in BUCKETS}}
                   for f in ITEM_FIELDS + HEADER_FIELDS},
        "forms_fully_correct": perfect_forms,
        "needs_review": needs_review,
        "invoicing_frequency_source": dict(freq_source),
        "total_cost_usd": round(cost, 4),
        "failures": {"items": item_errors, **{f: m for f, m in field_misses.items() if m}},
        "flagged_items": flagged_items,
    }

    md = [f"# Eval: {run_dir.name}", "",
          f"Forms: {n_forms} | fully correct: {perfect_forms} | needs_review: {needs_review} | cost: ${cost:.2f}", "",
          "## Item detection", "",
          "Products are scored like the fields: unflagged SKUs give precision and recall; a SKU flagged "
          "ambiguous with the expected SKU among its candidates is counted in its own column, as neither "
          "correct nor wrong.", "",
          "| | Precision | Recall | F1 | TP | FP | FN | Flagged ambiguous |", "|---|---|---|---|---|---|---|---|",
          f"| All forms | {prec:.1%} | {rec:.1%} | {f1:.1%} | {tp} | {fp} | {fn} | "
          + (f"{flagged['n']} (expected SKU as the value: {flagged['value']}, "
             f"among the alternatives: {flagged['alternative']})" if flagged["n"] else "-") + " |",
          f"| Near-twin forms ({twin['forms']}) | {twin_p:.1%} | {twin_r:.1%} | | | | | {twin['flagged'] or '-'} |",
          "", "(Near-twin forms: a catalog name that isn't sold overlaps a sold one.)", "",
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
    if flagged_items:
        md += ["### SKUs flagged ambiguous (not failures)"] + [f"- {e}" for e in flagged_items] + [""]
    for f in ITEM_FIELDS + HEADER_FIELDS:
        if field_misses[f]:
            md += [f"### {f} ({len(field_misses[f])})"] + [f"- {m}" for m in field_misses[f]] + [""]
    return result, md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--dataset", type=Path, default=Path("synthetic_order_form_dataset_50"))
    args = ap.parse_args()
    result, md = score_run(args.run_dir, args.dataset)
    (args.run_dir / "eval.json").write_text(json.dumps(result, indent=2))
    (args.run_dir / "eval.md").write_text("\n".join(md))
    print("\n".join(md[:30]))


if __name__ == "__main__":
    main()
