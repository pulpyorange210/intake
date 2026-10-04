"""Agent loop: the model reads the order form, uses compute for arithmetic, and submits;
the validator bounces errors and warnings back until the submission is accepted or the
retry cap is hit, in which case the last submission is returned flagged needs_review."""
from __future__ import annotations

import base64
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
from .pages import MAX_FULL_PAGES, PageIndex
from .pdf import cents, dates_in, extract_text, has_text_layer, numbers_in, pdf_base64
from .postprocess import build_output
from .schema import Submission, submission_json_schema
from .validator import Issue, ValidationContext, active_issues, validate

DEFAULT_MODEL = "claude-opus-5"
MAX_SUBMISSIONS = 3
MAX_TURNS = 12
MAX_TURNS_LONG = 24  # long documents: extra turns for search_document / read_pages

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
    per_turn: List[dict] = field(default_factory=list)

    def add(self, u) -> None:
        turn = {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
                "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}
        self.per_turn.append(turn)
        self.input_tokens += turn["input"]
        self.output_tokens += turn["output"]
        self.cache_creation_input_tokens += turn["cache_write"]
        self.cache_read_input_tokens += turn["cache_read"]

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
    index: Optional[PageIndex] = None  # set for long documents shown in part
    pages_read: List[int] = field(default_factory=list)   # fetched with read_pages
    pages_seen: List[int] = field(default_factory=list)   # sent up front or fetched
    searches: int = 0
    catalog_searches: List[dict] = field(default_factory=list)  # {"query", "candidates"} per search_catalog call


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
    issues = active_issues(all_issues, sub, session.ctx)
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


def _search_catalog(session: Session, line_text: str):
    text, codes = session.ctx.catalog.search_text(line_text)
    session.catalog_searches.append({"query": line_text, "candidates": codes})
    return text, False


def _search(session: Session, query: str):
    session.searches += 1
    return session.index.search(query), False


def _read_pages(session: Session, first, last):
    try:
        pages, note = session.index.read_range(first, last)
    except (TypeError, ValueError):
        return "first and last must be page numbers.", True
    if not pages:
        return note, True
    session.pages_read += [p for p in pages if p not in session.pages_read]
    session.pages_seen += [p for p in pages if p not in session.pages_seen]
    data = base64.standard_b64encode(session.index.pdf_of(pages)).decode("ascii")
    return [
        {"type": "text", "text": f"Pages {pages[0]}-{pages[-1]} of {session.index.n_pages}{note}. The PDF below "
                                 f"contains exactly these pages; their text layer follows it.\n"},
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
        {"type": "text", "text": session.index.labelled_text(pages)},
    ], False


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


LONG_DOC_MODES = ("outline", "select")
CATALOG_MODES = ("auto", "inline", "retrieval")


def parse_order_form(pdf_path: Path, catalog: Catalog, client: anthropic.Anthropic,
                     model: str = DEFAULT_MODEL, effort: str = "high",
                     transcript_path: Optional[Path] = None, long_doc: str = "outline",
                     catalog_mode: str = "auto") -> dict:
    """long_doc: how documents over MAX_FULL_PAGES are shown. "outline": a code-built outline only; the model
    fetches pages with read_pages. "select": the highest-scoring pages are sent up front (v0.9)."""
    """catalog_mode: "auto" puts catalogs of up to INLINE_LIMIT SKUs in the prompt and searches larger ones;
    "inline" / "retrieval" force one or the other."""
    if long_doc not in LONG_DOC_MODES:
        raise ValueError(f"long_doc must be one of {LONG_DOC_MODES}")
    if catalog_mode not in CATALOG_MODES:
        raise ValueError(f"catalog_mode must be one of {CATALOG_MODES}")
    pdf_path = Path(pdf_path)
    text = extract_text(pdf_path)
    session = Session(ValidationContext(catalog, text, numbers_in(text), set(), has_text_layer(text),
                                        dates_in(text)))
    retrieval = catalog_mode == "retrieval" or (catalog_mode == "auto" and not catalog.inline)
    system = prompts.system_prompt(catalog, retrieval)
    tools = [
        prompts.COMPUTE_TOOL,
        {"name": "submit_extraction", "description": prompts.SUBMIT_TOOL_DESCRIPTION,
         "input_schema": submission_json_schema()},
    ]
    if retrieval:
        tools.append(prompts.SEARCH_CATALOG_TOOL)
    selected = None
    if session.ctx.has_text_layer:
        index = PageIndex.build(pdf_path, text, [e.get("name") for e in catalog.entries])
        if index.n_pages > MAX_FULL_PAGES:
            # Long document: show the likeliest pages and let the model fetch the rest. Amounts and dates are
            # still checked against the whole document's text (session.ctx above).
            session.index = index
            session.ctx.partial_view = True
            tools += [prompts.SEARCH_TOOL, prompts.READ_PAGES_TOOL]

    outline = None
    if session.index and long_doc == "outline":
        outline = session.index.outline()
        content = [{"type": "text", "text": prompts.LONG_DOC_OUTLINE_TEMPLATE.format(
            filename=pdf_path.name, total=session.index.n_pages, outline=outline)}]
    elif session.index:
        selected = session.index.select()
        pages = list(selected)
        session.pages_seen += pages
        pdf_data = base64.standard_b64encode(session.index.pdf_of(pages)).decode("ascii")
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data}},
            {"type": "text", "text": prompts.LONG_DOC_TEMPLATE.format(
                filename=pdf_path.name, total=session.index.n_pages, pages=", ".join(map(str, pages)),
                text=session.index.labelled_text(pages))},
        ]
    else:
        if not session.ctx.has_text_layer:
            text = "(no text layer - the PDF appears to be scanned; read it from the page images)"
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": pdf_base64(pdf_path)}},
            {"type": "text", "text": prompts.USER_TEMPLATE.format(filename=pdf_path.name, text=text)},
        ]
    messages = [{"role": "user", "content": content}]
    max_turns = MAX_TURNS_LONG if session.index else MAX_TURNS

    usage = Usage()
    started = time.time()
    turns = 0
    stop_note = None
    while turns < max_turns and not session.accepted and session.submissions < MAX_SUBMISSIONS:
        turns += 1
        response = _call_model(
            client,
            model=model,
            max_tokens=32000,
            # Cache point after the system prompt (rules + catalog): identical for every form with the same
            # catalog, so later forms read it from the cache instead of re-writing it. Tools render before
            # the system prompt, so they are part of this cached prefix too.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
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
            elif tu.name == "search_catalog" and retrieval:
                content, is_error = _search_catalog(session, tu.input.get("line_text", ""))
            elif tu.name == "search_document" and session.index:
                content, is_error = _search(session, tu.input.get("query", ""))
            elif tu.name == "read_pages" and session.index:
                content, is_error = _read_pages(session, tu.input.get("first"), tu.input.get("last"))
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
    output["meta"]["catalog"] = {"mode": "retrieval" if retrieval else "inline", "size": len(catalog.entries),
                                 "searches": session.catalog_searches}
    if session.index:
        output["meta"]["long_document"] = {
            "mode": long_doc,
            "pages_total": session.index.n_pages,
            "outline_lines": len(outline.splitlines()) if outline else None,
            "pages_sent": selected,
            "pages_read": session.pages_read,
            "pages_seen": sorted(session.pages_seen),
            "searches": session.searches,
        }

    if transcript_path:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        # Drop the base64 PDF from the saved transcript to keep files small.
        saved = json.loads(json.dumps(messages, default=str))
        for message in saved:
            for block in message["content"] if isinstance(message["content"], list) else []:
                for inner in [block] + (block.get("content") if isinstance(block.get("content"), list) else []):
                    if inner.get("type") == "document":
                        inner["source"] = f"<pdf omitted: {pdf_path.name}>"
        transcript_path.write_text(json.dumps({"system": system, "messages": saved, "output": output}, indent=2))
    return output
