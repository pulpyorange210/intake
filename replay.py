"""Replay a saved run's transcripts through the current checker and post-processing, with no API calls.

Each transcript's compute calls and submissions are re-applied in order, so amount grounding sees the
same computed numbers the live run did. Reports, per form, what the current code would flag on the
final submission.

  python replay.py runs/v0.7 [--dataset synthetic_order_form_dataset_50]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ofparser.agent import Session, _compute, _submit
from ofparser.catalog import Catalog
from ofparser.pdf import dates_in, extract_text, has_text_layer, numbers_in
from ofparser.postprocess import build_output
from ofparser.validator import ValidationContext


def replay_form(transcript: dict, pdf: Path, catalog: Catalog):
    text = extract_text(pdf)
    session = Session(ValidationContext(catalog, text, numbers_in(text), set(), has_text_layer(text),
                                        dates_in(text)))
    for message in transcript["messages"]:
        if message["role"] != "assistant":
            continue
        for block in message["content"]:
            if block.get("type") != "tool_use":
                continue
            if block["name"] == "compute":
                _compute(session, block["input"].get("expression", ""))
            elif block["name"] == "submit_extraction":
                _submit(session, block["input"])
    if session.last_submission is None:
        return None, []
    unresolved = [] if session.accepted else session.last_issues
    return build_output(session.last_submission, catalog, unresolved, session.last_notes), session.last_issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--dataset", type=Path, default=Path("synthetic_order_form_dataset_50"))
    args = ap.parse_args()
    catalog = Catalog.load(args.dataset / "sku_catalog.json")

    fired, flagged = Counter(), []
    for path in sorted((args.run_dir / "transcripts").glob("*.json")):
        form = path.stem
        output, issues = replay_form(json.loads(path.read_text()), args.dataset / "pdfs" / f"{form}.pdf", catalog)
        if output is None:
            print(f"{form}: no submission in transcript")
            continue
        for issue in issues:
            fired[(issue.severity, issue.check)] += 1
            print(f"{form}: {issue.severity} {issue.check} item {issue.item_index}: {issue.message}")
        if output["needs_review"]:
            flagged.append(form)
            for note in output["review_notes"]:
                if note["check"] in ("missing_value", "date_not_in_document"):
                    print(f"{form}: needs_review - item {note['item_index']}: {note['message']}")

    print(f"\nIssues on final submissions: {dict(fired) or 'none'}")
    print(f"needs_review: {len(flagged)} form(s) {flagged}")


if __name__ == "__main__":
    main()
