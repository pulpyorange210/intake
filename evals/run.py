"""Eval gate: run extraction over the eval set, compare to the expected JSON, and fail on regressions.

  python evals/run.py                      # replay mode: recorded model responses, no API key, deterministic
  python evals/run.py --mode live          # real API over the full set (costs about $0.17 per form)
  python evals/run.py --record             # live, and refresh evals/cassettes/ from the run
  python evals/run.py --update-baseline    # after an intended change: make this report the new baseline
  python evals/run.py --import-run runs/v0.8   # turn a parse.py run's transcripts into cassettes

Writes evals/report.json and evals/report.md. Exits 1 if any threshold in evals/thresholds.yaml fails, and
names the forms and fields that got worse compared with evals/baseline.json.

Replay mode catches any regression in the non-LLM code (grounding, checker, post-processing, matching): the
recorded tool calls go through the current code, and a recorded answer the current checker would reject comes
out needs_review. It can't catch a prompt or model change; that needs --mode live.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import tempfile
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval import match_items, read_field  # noqa: E402
from ofparser import cassette  # noqa: E402
from ofparser.catalog import Catalog  # noqa: E402
from ofparser.postprocess import sku_value  # noqa: E402

EVALS = ROOT / "evals"
CASSETTES = EVALS / "cassettes"

# The eval set: the 50 synthetic forms, plus the real redacted form (different layout, its own catalog, and an
# expected answer covering contract items only).
SYNTHETIC = ROOT / "synthetic_order_form_dataset_50"
REAL = ROOT / "edge_cases" / "example_order_form_redacted"


def eval_set() -> List[dict]:
    forms = [{"id": pdf.stem, "pdf": pdf, "expected": SYNTHETIC / "ground_truth" / f"{pdf.stem}.json",
              "catalog": SYNTHETIC / "sku_catalog.json"} for pdf in sorted((SYNTHETIC / "pdfs").glob("*.pdf"))]
    forms.append({"id": "example_order_form_redacted", "pdf": REAL / "input.pdf", "expected": REAL / "expected.json",
                  "catalog": REAL / "catalog.json"})
    return forms


# Fields where a confident wrong answer is a wrong value: amounts, dates and billing terms. A value flagged
# ambiguous (with the alternative next to it) or left blank with the doubt recorded is not wrong; it is
# counted separately, as in eval.py.
AMOUNT_FIELDS = ("currency", "total_listed_value", "quantity", "unit_price")
DATE_FIELDS = ("service_start_date", "service_end_date")
BILLING_FIELDS = ("invoicing_frequency",)
ITEM_FIELDS = AMOUNT_FIELDS + DATE_FIELDS + BILLING_FIELDS
HEADER_FIELDS = ("effective_date", "contract_signed_date_buying_company", "contract_signed_date_selling_company")


def normalize(field: str, value):
    """Compare numbers after normalising them and dates as ISO dates; everything else as trimmed lowercase."""
    if value is None:
        return None
    if field in ("total_listed_value", "unit_price", "quantity"):
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return str(value)
    if field.endswith("_date"):
        try:
            return dt.date.fromisoformat(str(value).strip())
        except ValueError:
            return str(value)
    return " ".join(str(value).split()).lower()


def score_form(form_id: str, output: dict, expected: dict) -> dict:
    gold = [dict(g, sku_code=g.get("sku_code") or g.get("sku_reference")) for g in expected["contract_items"]]
    pred = output.get("contract_items") or []
    pairs, flagged_pairs, extra, missed = match_items(pred, gold)
    result = {"form": form_id, "items_expected": len(gold), "items_found": len(pairs) + len(flagged_pairs),
              "flagged_skus": len(flagged_pairs),
              "wrong_skus": [sku_value(pred[i]["sku_code"]) for i in extra],
              "missed_items": [gold[i]["sku_code"] for i in missed],
              "wrong_values": [], "missing_values": [], "flagged_values": 0,
              "needs_review": bool(output.get("needs_review")),
              "cost_usd": (output.get("meta") or {}).get("cost_usd"),
              "seconds": (output.get("meta") or {}).get("seconds")}

    def check(where: str, obj: dict, gold_obj: dict, fields):
        for f in fields:
            if f not in gold_obj or gold_obj[f] is None:
                continue
            value, bucket = read_field(obj, f)
            if bucket != "unflagged":
                result["flagged_values"] += 1
            elif value is None:
                result["missing_values"].append({"where": where, "field": f, "expected": gold_obj[f]})
            elif normalize(f, value) != normalize(f, gold_obj[f]):
                result["wrong_values"].append({"where": where, "field": f, "got": value, "expected": gold_obj[f]})

    for pi, gi in pairs + flagged_pairs:
        check(gold[gi]["sku_code"], pred[pi], gold[gi], ITEM_FIELDS)
    check("order_form", output.get("order_form") or {}, expected, HEADER_FIELDS)
    return result


def summarize(forms: List[dict]) -> dict:
    expected = sum(f["items_expected"] for f in forms)
    costs = [f["cost_usd"] for f in forms if f["cost_usd"] is not None]
    seconds = [f["seconds"] for f in forms if f["seconds"] is not None]
    return {
        "forms": len(forms),
        "line_item_recall": sum(f["items_found"] for f in forms) / expected if expected else 1.0,
        "wrong_values": sum(len(f["wrong_values"]) for f in forms),
        "wrong_sku_matches": sum(len(f["wrong_skus"]) for f in forms),
        "no_review_forms": sum(not f["needs_review"] for f in forms),
        "missing_values": sum(len(f["missing_values"]) for f in forms),
        "flagged_values": sum(f["flagged_values"] for f in forms),
        "flagged_skus": sum(f["flagged_skus"] for f in forms),
        "cost_per_form_usd": round(statistics.mean(costs), 4) if costs else None,
        "seconds_per_form": round(statistics.mean(seconds), 1) if seconds else None,
    }


def load_thresholds(path: Path) -> Dict[str, float]:
    """thresholds.yaml is flat `key: number  # comment` lines, so it needs no YAML library."""
    out = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            key, value = (part.strip() for part in line.split(":", 1))
            out[key] = float(value)
    return out


def check_thresholds(summary: dict, thresholds: Dict[str, float]) -> List[str]:
    """Each threshold key names a summary metric; *_min / *_max suffixes set the direction, and a bare key on a
    count of errors is a maximum (wrong_values: 0) while a bare key on a rate is a minimum (recall: 1.0)."""
    failures = []
    for key, limit in thresholds.items():
        if key.endswith("_max_usd"):
            metric, is_max = key[: -len("_max_usd")] + "_usd", True
        elif key.endswith("_min") or key.endswith("_max"):
            metric, is_max = key[:-4], key.endswith("_max")
        else:
            metric, is_max = key, key.startswith("wrong_")
        value = summary.get(metric)
        if value is None:
            continue
        if (is_max and value > limit) or (not is_max and value < limit):
            failures.append(f"{metric} = {value:g} ({'max' if is_max else 'min'} {limit:g})")
    return failures


def regressions(forms: List[dict], baseline: Optional[dict]) -> List[str]:
    """What got worse per form compared with the committed baseline."""
    if not baseline:
        return []
    before = {f["form"]: f for f in baseline.get("forms", [])}
    lines = []
    for f in forms:
        b = before.get(f["form"])
        if b is None:
            continue
        key = lambda v: (v["where"], v["field"], str(v.get("got")))
        old_wrong = {key(v) for v in b["wrong_values"]}
        for v in f["wrong_values"]:
            if key(v) not in old_wrong:
                lines.append(f"{f['form']}: {v['where']} {v['field']} is {v['got']!r}, expected {v['expected']!r}")
        old_missing = {(v["where"], v["field"]) for v in b["missing_values"]}
        for v in f["missing_values"]:
            if (v["where"], v["field"]) not in old_missing:
                lines.append(f"{f['form']}: {v['where']} {v['field']} is now blank (expected {v['expected']!r})")
        for sku in set(f["missed_items"]) - set(b["missed_items"]):
            lines.append(f"{f['form']}: item {sku} no longer found")
        for sku in set(f["wrong_skus"]) - set(b["wrong_skus"]):
            lines.append(f"{f['form']}: extra or wrong SKU {sku}")
        if f["needs_review"] and not b["needs_review"]:
            lines.append(f"{f['form']}: now needs review ({f.get('review_reason') or 'see report'})")
    return lines


def review_reason(output: dict) -> Optional[str]:
    issues = output.get("unresolved_issues") or []
    if issues:
        return "; ".join(f"[{i['check']}] {i['message']}" for i in issues[:2])
    notes = [n for n in output.get("review_notes") or []
             if n["check"] in ("missing_value", "date_not_in_document", "sku_ambiguous")]
    return "; ".join(f"[{n['check']}] {n['message'][:120]}" for n in notes[:2]) or None


def run_live(form: dict, catalog: Catalog, record_dir: Optional[Path]) -> dict:
    import anthropic

    from ofparser.agent import parse_order_form
    with tempfile.TemporaryDirectory() as tmp:
        transcript_path = Path(tmp) / "t.json"
        output = parse_order_form(form["pdf"], catalog, anthropic.Anthropic(), transcript_path=transcript_path)
        if record_dir:
            record_dir.mkdir(parents=True, exist_ok=True)
            tape = cassette.from_transcript(json.loads(transcript_path.read_text()), form["pdf"], output)
            tape["form"] = form["id"]
            (record_dir / f"{form['id']}.json").write_text(json.dumps(tape, indent=1))
    return output


def import_run(run_dir: Path, out_dir: Path) -> int:
    """Turn a parse.py run (transcripts/ + outputs/) into cassettes for the forms of the eval set."""
    by_stem = {}
    for form in eval_set():
        by_stem.setdefault(form["pdf"].stem, form)
    n = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted((run_dir / "transcripts").glob("*.json")):
        form = by_stem.get(path.stem)
        if form is None:
            continue
        output_path = run_dir / "outputs" / path.name
        output = json.loads(output_path.read_text()) if output_path.exists() else None
        tape = cassette.from_transcript(json.loads(path.read_text()), form["pdf"], output)
        tape["form"] = form["id"]
        (out_dir / f"{form['id']}.json").write_text(json.dumps(tape, indent=1))
        n += 1
    return n


def to_markdown(summary: dict, thresholds: Dict[str, float], failures: List[str], regressed: List[str],
                mode: str, forms: List[dict]) -> str:
    pct = lambda x: f"{x:.1%}"
    rows = [
        ("Line-item recall", pct(summary["line_item_recall"]), "line_item_recall"),
        ("Wrong values (amounts, dates, billing terms)", summary["wrong_values"], "wrong_values"),
        ("Wrong SKU matches", summary["wrong_sku_matches"], "wrong_sku_matches"),
        ("Forms needing no review", f"{summary['no_review_forms']} / {summary['forms']}", "no_review_forms_min"),
        ("Cost per form", f"${summary['cost_per_form_usd']:.3f}" if summary["cost_per_form_usd"] is not None
         else "-", "cost_per_form_max_usd"),
        ("Time per form", f"{summary['seconds_per_form']} s" if summary["seconds_per_form"] is not None else "-",
         None),
    ]
    md = [f"## Eval: {'PASS' if not failures else 'FAIL'} ({mode} mode, {summary['forms']} forms)", "",
          "| Metric | Result | Threshold |", "|---|---|---|"]
    for label, value, key in rows:
        md.append(f"| {label} | {value} | {thresholds[key]:g} |" if key in thresholds
                  else f"| {label} | {value} | - |")
    md += ["", f"Not counted as wrong: {summary['flagged_values']} values flagged ambiguous, "
               f"{summary['flagged_skus']} SKUs flagged ambiguous, {summary['missing_values']} values left blank.",
           ""]
    if mode == "replay":
        md += ["Replay mode: cost and time are from the recorded live runs; the checker, post-processing and "
               "matching ran on the current code.", ""]
    if failures:
        md += ["### Failed thresholds", ""] + [f"- {f}" for f in failures] + [""]
    if regressed:
        md += ["### Regressions vs baseline", ""] + [f"- {r}" for r in regressed] + [""]
    review = [f for f in forms if f["needs_review"]]
    if review:
        md += ["### Forms needing review", ""] + [f"- {f['form']}: {f.get('review_reason')}" for f in review] + [""]
    return "\n".join(md)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("--record", action="store_true", help="live run that rewrites the cassettes")
    ap.add_argument("--cassettes", type=Path, default=CASSETTES)
    ap.add_argument("--forms", nargs="*", help="only these form ids")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--import-run", type=Path, help="convert a parse.py run's transcripts into cassettes and exit")
    ap.add_argument("--out", type=Path, default=EVALS, help="where report.json / report.md go")
    args = ap.parse_args()

    if args.import_run:
        print(f"imported {import_run(args.import_run, args.cassettes)} cassettes into {args.cassettes}")
        return 0
    mode = "live" if args.record else args.mode
    forms = [f for f in eval_set() if not args.forms or f["id"] in args.forms]
    catalogs: Dict[Path, Catalog] = {}
    results, started = [], time.time()
    for form in forms:
        catalog = catalogs.setdefault(form["catalog"], Catalog.load(form["catalog"]))
        if mode == "live":
            output = run_live(form, catalog, args.cassettes if args.record else None)
        else:
            tape_path = args.cassettes / f"{form['id']}.json"
            if not tape_path.exists():
                print(f"{form['id']}: no cassette, skipped (record one with --record --forms {form['id']})")
                continue
            output = cassette.replay(cassette.load(tape_path), form["pdf"], catalog)
        result = score_form(form["id"], output, json.loads(form["expected"].read_text()))
        result["review_reason"] = review_reason(output) if result["needs_review"] else None
        results.append(result)

    summary = summarize(results)
    thresholds = load_thresholds(EVALS / "thresholds.yaml")
    failures = check_thresholds(summary, thresholds)
    baseline_path = EVALS / "baseline.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
    regressed = regressions(results, baseline)
    report = {"mode": mode, "run_seconds": round(time.time() - started, 1), "summary": summary,
              "thresholds": thresholds, "failed": failures, "regressions": regressed, "forms": results}
    md = to_markdown(summary, thresholds, failures, regressed, mode, results)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=1, default=str))
    (args.out / "report.md").write_text(md + "\n")
    if args.update_baseline:
        baseline_path.write_text(json.dumps({"summary": summary, "forms": results}, indent=1, default=str))
        print(f"baseline updated: {baseline_path}")
    print(md)
    print(f"({report['run_seconds']} s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
