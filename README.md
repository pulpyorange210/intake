# Order Form Parser

Takes an order form PDF and a SKU catalog and returns the order form details (dates, parties, total)
plus the contract items, each mapped to a SKU in the catalog. Built on the Claude API as a small agent:
the model reads the document, does its arithmetic through a tool, and submits its answer to a checker
that sends it back if something doesn't add up.

## Results

Measured on the 50 synthetic order forms in `synthetic_order_form_dataset_50/` (`runs/v0.7`, cost $8.18 total,
about a minute per form).

**Finding the right items:** 132 of 132 contract items found, no extra items (100% precision and recall).
This includes 20 forms where a catalog item that isn't sold has a very similar name to one that is.

**Field accuracy** (per matched item, against the ground truth):

| Field | Accuracy |
|---|---|
| Currency, total value, quantity, unit price | 100% (money compared exactly, to the cent) |
| Service start / end date | 100% |
| Payment terms | 100% |
| Invoicing frequency | 104/104 correct, plus 28 flagged as ambiguous (see below) |
| Effective date | 49/49 correct, 1 left blank as ambiguous |
| Buyer / seller signature dates | 100% |
| Invoicing schedule type | 0% |
| Special notes | 0% |

Some honest caveats:

- These are the same 50 forms I used while developing, so the numbers are on the optimistic side.
  I tried to keep every fix general (no phrases copied from these PDFs in the code or prompts), but
  it hasn't been tested on a different set of forms.
- **Invoicing schedule type and special notes** score 0% because the ground-truth values for them
  aren't in the PDFs. The parser leaves schedule type empty rather than guessing. For special notes it
  picks up the form's "Up to Customer Employee Size" line, the same kind of note as the example
  ("Up to 25,000 employee size"), but the ground truth has unrelated phrases there.
- **Invoicing frequency:** 28 items have one price covering exactly 12 months. That's one invoice,
  but "one-time" and "yearly" both describe it, and nothing in the document settles which. The output
  says "one-time" and marks it ambiguous with "yearly" as the alternative. 19 of the 28 match the
  ground-truth label.
- **Effective date:** one form prints `06/04/2024` and nothing else in it tells you whether that's
  June 4 or April 6. The parser leaves it blank, marks it ambiguous, and notes June 4 as the likely
  reading because the form was signed June 7. June 4 is the correct answer.
- The real example form (`edge_cases/example_order_form_redacted/`) hasn't been run,
  because the PDF wasn't in the materials I had. The catalog and expected answer are there, ready.

The full breakdown with every failure is in `runs/v0.7/eval.md`, and `CHANGELOG.md` walks through each
version, what went wrong and what I changed.

## Running it

Needs Python 3.9+, poppler (`brew install poppler`, for `pdftotext`) and an Anthropic API key.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

# parse one form, or a whole folder
.venv/bin/python parse.py --catalog synthetic_order_form_dataset_50/sku_catalog.json path/to/form.pdf
.venv/bin/python parse.py --catalog synthetic_order_form_dataset_50/sku_catalog.json \
    synthetic_order_form_dataset_50/pdfs/*.pdf --out runs/mine

# score a run against the ground truth
.venv/bin/python eval.py runs/mine

# tests (no API calls)
.venv/bin/python -m unittest discover -s tests -t .
```

Each run folder gets `outputs/<form>.json` (the extraction), `transcripts/<form>.json` (the full
conversation with the model, useful for seeing why it chose something) and `run_meta.json`.

## How the code works

The flow for one PDF:

```
PDF -> text layer + the PDF itself -> agent loop -> checker -> post-processing -> JSON
                                          ^            |
                                          +-- errors --+
```

- **`parse.py`**: the command line. Loads the catalog, runs forms in parallel, writes the outputs.
- **`ofparser/pdf.py`**: pulls the text layer with `pdftotext -layout` (keeps table columns lined up).
  If there's no text layer (a scan), it says so, and the model reads the page images instead.
- **`ofparser/catalog.py`**: loads the SKU catalog.
- **`ofparser/prompts.py`**: the system prompt. The whole catalog goes in, including each SKU's
  parsing instructions, along with the rules: only extract items that are in the catalog, keep out
  anything the form says isn't sold, and flag real ambiguity instead of guessing.
- **`ofparser/agent.py`**: the agent loop. The model gets the PDF and its text, and has two tools:
  - `compute`: exact decimal arithmetic, so totals like "3 years x 255,000" aren't done in the model's head.
  - `submit_extraction`: hands in the answer. It gets checked, and if it fails the model gets the
    list of problems and tries again, up to 3 submissions. If it still fails, the output is returned
    with `needs_review: true`.
- **`ofparser/validator.py`**: the checker. Two kinds of issues:
  - Errors the model must fix: an amount that doesn't appear in the document and isn't a `compute`
    result from document numbers, a SKU that isn't in the catalog, invalid or reversed dates.
  - Warnings the model must fix or explain: unit price x quantity doesn't divide evenly into the
    total, an odd billing period length, items not adding up to the grand total, a required value
    left empty.
- **`ofparser/postprocess.py`**: turns the accepted submission into the final output. The main job is
  invoicing frequency: use it if the document states it, otherwise infer it from how the price
  is split (e.g. four quarterly prices -> quarterly), and mark it ambiguous when two labels fit.
- **`ofparser/schema.py`**: the output structure (Pydantic models).
- **`ofparser/compute.py`**: the arithmetic behind the `compute` tool.
- **`eval.py`**: scores a run against the ground truth. It matches items by SKU, compares fields
  exactly, and reports ambiguous answers separately so they don't inflate the main numbers.

## Output

Each form gives an `order_form` block (parties, effective date, signature dates, grand total) and a
list of `contract_items` with the fields (`sku_code` is the `sku_reference`).
Every value also carries the quote from the document it came from, under `evidence`. Trimmed
example:

```json
{
  "order_form": {
    "customer_name": "Summit Telecom",
    "effective_date": "2025-08-04",
    "contract_signed_date_buying_company": "2025-08-08",
    "contract_signed_date_selling_company": "2025-08-11",
    "grand_total": 120721.04
  },
  "contract_items_count": 1,
  "contract_items": [
    {
      "name": "Talent Intelligence Platform Premium Edition (Add-on)",
      "sku_code": "TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON",
      "currency": "USD",
      "total_listed_value": 120721.04,
      "quantity": 1.0,
      "unit_price": 30180.26,
      "unit_price_period": "quarter",
      "service_start_date": "2025-08-07",
      "service_end_date": "2026-08-06",
      "invoicing_frequency": {
        "value": "quarterly",
        "source": "inferred_from_pricing",
        "ambiguous": false,
        "alternatives": []
      },
      "payment_terms": "Net 55",
      "special_notes": "Up to Customer Employee Size: 2,500"
    }
  ]
}
```

When a field is ambiguous it's either left empty with the candidate readings listed under
`ambiguous_fields`, or, for invoicing frequency, given with `ambiguous: true` and the alternatives
next to it. Either way the output never looks more certain than it is.
