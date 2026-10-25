"""Write the eval results table into README.md from evals/report.json (between the eval-table markers).

  python evals/run.py && python evals/readme_table.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- eval-table:start -->", "<!-- eval-table:end -->"


def table(report: dict) -> str:
    s, t = report["summary"], report["thresholds"]
    rows = [
        ("Line-item recall", f"{s['line_item_recall']:.0%}", f"≥ {t['line_item_recall']:.0%}"),
        ("Wrong values (amounts, dates, billing terms)", s["wrong_values"], f"≤ {t['wrong_values']:g}"),
        ("Wrong SKU matches", s["wrong_sku_matches"], f"≤ {t['wrong_sku_matches']:g}"),
        ("Forms needing no review", f"{s['no_review_forms']} / {s['forms']}", f"≥ {t['no_review_forms_min']:g}"),
        ("Cost per form", f"${s['cost_per_form_usd']:.3f}", f"≤ ${t['cost_per_form_max_usd']:.2f}"),
        ("Time per form", f"{s['seconds_per_form']:.0f} s", "-"),
    ]
    lines = ["| Metric | Result | Gate |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in rows]
    lines += ["", f"Not counted as wrong: {s['flagged_values']} values flagged ambiguous with the alternative shown, "
                  f"{s['missing_values']} left blank. Generated from `evals/report.json` ({s['forms']} forms, "
                  f"{report['mode']} mode)."]
    return "\n".join(lines)


def main() -> None:
    report = json.loads((ROOT / "evals" / "report.json").read_text())
    readme = ROOT / "README.md"
    text = readme.read_text()
    new = re.sub(f"{re.escape(START)}.*?{re.escape(END)}", f"{START}\n{table(report)}\n{END}", text, flags=re.S)
    readme.write_text(new)
    print("README eval table updated" if new != text else "README eval table already current")


if __name__ == "__main__":
    main()
