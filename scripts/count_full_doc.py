"""Baseline for long documents: how many input tokens the current approach (whole PDF + whole text layer in the
first message) would send, measured with the token-counting API. Nothing is extracted; no model run.

The API accepts at most 600 PDF pages per request, so a longer PDF can't be counted (or sent) in one piece.
For those, the PDF is counted in 100-page chunks and summed, and the result is marked as over the limit.

  python scripts/count_full_doc.py edge_cases/long_document/generated/*.pdf
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

import anthropic
from pypdf import PdfReader, PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ofparser import prompts  # noqa: E402
from ofparser.agent import DEFAULT_MODEL, PRICING  # noqa: E402
from ofparser.catalog import Catalog  # noqa: E402
from ofparser.pdf import extract_text  # noqa: E402
from ofparser.schema import submission_json_schema  # noqa: E402

API_PAGE_LIMIT = 600
CHUNK = 100


def pdf_bytes(reader: PdfReader, start: int, end: int) -> bytes:
    writer = PdfWriter()
    for p in reader.pages[start:end]:
        writer.add_page(p)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def doc_block(data: bytes) -> dict:
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                           "data": base64.standard_b64encode(data).decode("ascii")}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--catalog", type=Path, default=Path("edge_cases/example_order_form_redacted/catalog.json"))
    args = ap.parse_args()
    client = anthropic.Anthropic()
    catalog = Catalog.load(args.catalog)
    system = prompts.SYSTEM_TEMPLATE.format(catalog=catalog.to_prompt())
    tools = [prompts.COMPUTE_TOOL, {"name": "submit_extraction", "description": prompts.SUBMIT_TOOL_DESCRIPTION,
                                    "input_schema": submission_json_schema()}]
    price_in = PRICING[DEFAULT_MODEL][0]

    def count(content) -> int:
        return client.messages.count_tokens(model=DEFAULT_MODEL, system=system, tools=tools,
                                            messages=[{"role": "user", "content": content}]).input_tokens

    base = count("x")  # system prompt + tools + a minimal message
    print(f"{'document':<16}{'pages':>6}  {'PDF tokens':>11}  {'text-layer tokens':>18}  {'first turn total':>17}  "
          f"{'cost (cache write)':>19}  fits in one request?")
    for path in args.pdfs:
        reader = PdfReader(str(path))
        n = len(reader.pages)
        pdf_tokens = sum(count([doc_block(pdf_bytes(reader, s, min(s + CHUNK, n)))]) - base
                         for s in range(0, n, CHUNK))
        text_tokens = count(prompts.USER_TEMPLATE.format(filename=path.name, text=extract_text(path))) - base
        total = base + pdf_tokens + text_tokens
        # first turn writes the whole prompt to the cache (1.25x input price), as the agent's auto-caching does
        cost = total * price_in * 1.25 / 1e6
        fits = "yes" if n <= API_PAGE_LIMIT and total <= 1_000_000 else (
            f"no: {n} pages > {API_PAGE_LIMIT}-page limit" if n > API_PAGE_LIMIT else "no: over 1M-token context")
        print(f"{path.stem:<16}{n:>6}  {pdf_tokens:>11,}  {text_tokens:>18,}  {total:>17,}  ${cost:>18.2f}  {fits}")


if __name__ == "__main__":
    main()
