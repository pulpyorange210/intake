"""Recorded model responses ("cassettes"), replayed through the current checker and post-processing.

A cassette keeps only what the model did: its tool calls in order (compute expressions and submissions) plus
the live run's usage and timing. Replaying re-applies them through the same tool handlers the live agent
uses, so every non-LLM part of the pipeline (grounding, checker, post-processing) runs for real, with no API
key and no randomness. What replay can't do is react: if the current checker rejects a recorded final
submission, there is no model to fix it, so the form comes out needs_review. That is the regression signal.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from .agent import Session, _compute, _submit
from .catalog import Catalog
from .pdf import dates_in, extract_text, has_text_layer, numbers_in
from .postprocess import build_output
from .validator import ValidationContext

REPLAYED_TOOLS = ("compute", "submit_extraction")


def pdf_sha256(pdf_path: Path) -> str:
    return hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()


def from_transcript(transcript: dict, pdf_path: Path, output: Optional[dict] = None) -> dict:
    """Build a cassette from a saved agent transcript (`parse.py` writes one per form)."""
    output = output if output is not None else transcript.get("output") or {}
    calls = []
    for message in transcript["messages"]:
        if message["role"] != "assistant" or not isinstance(message["content"], list):
            continue
        for block in message["content"]:
            if block.get("type") == "tool_use" and block.get("name") in REPLAYED_TOOLS:
                calls.append({"name": block["name"], "input": block["input"]})
    meta = output.get("meta") or {}
    return {
        "form": Path(pdf_path).stem,
        "pdf_sha256": pdf_sha256(pdf_path),
        "recorded": {k: meta.get(k) for k in ("model", "effort", "turns", "submissions", "seconds", "usage",
                                              "cost_usd")},
        "tool_calls": calls,
    }


def replay(cassette: dict, pdf_path: Path, catalog: Catalog) -> dict:
    """Run a cassette's tool calls through the current code and return the output, like parse_order_form."""
    text = extract_text(pdf_path)
    session = Session(ValidationContext(catalog, text, numbers_in(text), set(), has_text_layer(text),
                                        dates_in(text)))
    for call in cassette["tool_calls"]:
        if session.accepted:
            break
        if call["name"] == "compute":
            _compute(session, call["input"].get("expression", ""))
        elif call["name"] == "submit_extraction":
            _submit(session, call["input"])
    if session.last_submission is None:
        output = {"order_form": None, "contract_items_count": 0, "contract_items": [], "needs_review": True,
                  "unresolved_issues": [{"severity": "error", "check": "no_submission", "item_index": None,
                                         "message": "the recording has no valid submission"}],
                  "review_notes": []}
    else:
        unresolved = [] if session.accepted else session.last_issues
        output = build_output(session.last_submission, catalog, unresolved, session.last_notes)
    recorded = cassette.get("recorded") or {}
    output["meta"] = {"source_pdf": Path(pdf_path).name, "replayed": True, **recorded}
    return output


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())
