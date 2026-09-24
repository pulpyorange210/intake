"""Agent loop: the model reads the order form, uses compute for arithmetic, and submits;
the validator bounces errors and warnings back until the submission is accepted or the
retry cap is hit, in which case the last submission is returned flagged needs_review."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Set

import anthropic
import httpx
from pydantic import ValidationError

from . import prompts
from .catalog import Catalog
from .compute import ComputeError, evaluate
from .pdf import cents, extract_text, numbers_in, pdf_base64
from .postprocess import build_output
from .schema import Submission, submission_json_schema
from .validator import Issue, ValidationContext, active_issues, validate

DEFAULT_MODEL = "claude-opus-5"
MAX_SUBMISSIONS = 3
MAX_TURNS = 12

# $ per million tokens: (input, output). Cache writes bill at 1.25x input, reads at 0.1x.
PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, u) -> None:
        self.input_tokens += u.input_tokens or 0
        self.output_tokens += u.output_tokens or 0
        self.cache_creation_input_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.cache_read_input_tokens += getattr(u, "cache_read_input_tokens", 0) or 0

    def cost(self, model: str) -> Optional[float]:
        if model not in PRICING:
            return None
        inp, out = PRICING[model]
        return round((self.input_tokens * inp + self.cache_creation_input_tokens * inp * 1.25
                      + self.cache_read_input_tokens * inp * 0.1 + self.output_tokens * out) / 1e6, 4)


@dataclass
class Session:
    """Per-document state shared by the tools."""
    ctx: ValidationContext
    computed: Set[Decimal] = field(default_factory=set)
    submissions: int = 0
    last_submission: Optional[Submission] = None
    last_issues: List[Issue] = field(default_factory=list)
    last_notes: List[Issue] = field(default_factory=list)
    accepted: bool = False


def _compute(session: Session, expression: str):
    try:
        value, grounded = evaluate(expression, session.ctx.doc_numbers | session.computed)
    except ComputeError as exc:
        return str(exc), True
    if grounded:
        session.computed.add(cents(value))
        session.ctx.computed_numbers = session.computed
    note = "" if grounded else " (note: some operands are not document values; result is not treated as grounded)"
    return f"{expression} = {value} (rounded to cents: {cents(value)}){note}", False


def _submit(session: Session, payload: dict):
    try:
        sub = Submission.model_validate(payload)
    except ValidationError as exc:
        return f"Schema errors (hard, must fix):\n{exc}", True
    session.submissions += 1
    session.last_submission = sub
    all_issues = validate(sub, session.ctx)
    session.last_notes = [i for i in all_issues if i.severity == "note"]
    issues = active_issues(all_issues, sub)
    session.last_issues = issues
    if not issues:
        session.accepted = True
        return "accepted", False
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    lines = [f"Submission {session.submissions}/{MAX_SUBMISSIONS} not accepted."]
    if errors:
        lines.append("Hard errors (must fix):")
        lines += [f"- [{i.check}] item {i.item_index}: {i.message}" for i in errors]
    if warnings:
        lines.append("Warnings (fix if wrong; if correct as written, resubmit with an override "
                     "{check, item_index, reason}):")
        lines += [f"- [{i.check}] item {i.item_index}: {i.message}" for i in warnings]
    return "\n".join(lines), True


STREAM_RETRIES = 4


def _call_model(client: anthropic.Anthropic, **params):
    """One streamed model turn. The SDK retries failed requests, but not a stream that drops
    mid-body; a turn has no side effects until its tool calls run, so re-issuing it is safe."""
    for attempt in range(STREAM_RETRIES):
        try:
            with client.beta.messages.stream(**params) as stream:
                return stream.get_final_message()
        except (anthropic.APIConnectionError, httpx.TransportError):
            if attempt == STREAM_RETRIES - 1:
                raise
            time.sleep(2 ** attempt * 5)


def _block_to_dict(block) -> dict:
    return block.model_dump(mode="json", exclude_none=True) if hasattr(block, "model_dump") else block


def parse_order_form(pdf_path: Path, catalog: Catalog, client: anthropic.Anthropic,
                     model: str = DEFAULT_MODEL, effort: str = "high",
                     transcript_path: Optional[Path] = None) -> dict:
    pdf_path = Path(pdf_path)
    text = extract_text(pdf_path)
    session = Session(ValidationContext(catalog, text, numbers_in(text), set()))

    system = prompts.SYSTEM_TEMPLATE.format(catalog=catalog.to_prompt())
    tools = [
        prompts.COMPUTE_TOOL,
        {"name": "submit_extraction", "description": prompts.SUBMIT_TOOL_DESCRIPTION,
         "input_schema": submission_json_schema()},
    ]
    messages = [{
        "role": "user",
        "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": pdf_base64(pdf_path)}},
            {"type": "text", "text": prompts.USER_TEMPLATE.format(filename=pdf_path.name, text=text)},
        ],
    }]

    usage = Usage()
    started = time.time()
    turns = 0
    stop_note = None
    while turns < MAX_TURNS and not session.accepted and session.submissions < MAX_SUBMISSIONS:
        turns += 1
        response = _call_model(
            client,
            model=model,
            max_tokens=32000,
            system=system,
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        usage.add(response.usage)
        messages.append({"role": "assistant", "content": [_block_to_dict(b) for b in response.content]})

        if response.stop_reason == "refusal":
            stop_note = "model refused"
            break
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            if response.stop_reason == "max_tokens":
                stop_note = "hit max_tokens"
                break
            messages.append({"role": "user", "content": "Call submit_extraction with your extraction."})
            continue

        results = []
        for tu in tool_uses:
            if tu.name == "compute":
                content, is_error = _compute(session, tu.input.get("expression", ""))
            elif tu.name == "submit_extraction":
                content, is_error = _submit(session, tu.input)
            else:
                content, is_error = f"unknown tool {tu.name}", True
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})

    if session.last_submission is None:
        output = {"order_form": None, "contract_items_count": 0, "contract_items": [], "needs_review": True,
                  "unresolved_issues": [{"severity": "error", "check": "no_submission", "item_index": None,
                                         "message": stop_note or "agent never produced a valid submission"}]}
    else:
        unresolved = [] if session.accepted else session.last_issues
        output = build_output(session.last_submission, catalog, unresolved, session.last_notes)
    output["meta"] = {
        "source_pdf": pdf_path.name,
        "model": model,
        "effort": effort,
        "turns": turns,
        "submissions": session.submissions,
        "stop_note": stop_note,
        "seconds": round(time.time() - started, 1),
        "usage": usage.__dict__,
        "cost_usd": usage.cost(model),
    }

    if transcript_path:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        # Drop the base64 PDF from the saved transcript to keep files small.
        saved = json.loads(json.dumps(messages, default=str))
        saved[0]["content"][0] = {"type": "document", "source": f"<pdf omitted: {pdf_path.name}>"}
        transcript_path.write_text(json.dumps({"system": system, "messages": saved, "output": output}, indent=2))
    return output
