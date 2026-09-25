# Order Form Parser

Takes an order form PDF and a SKU catalog and returns the order form details (dates, parties, total)
plus the contract items, each mapped to a SKU in the catalog. Built on the Claude API as a small agent:
the model reads the document, does its arithmetic through a tool, and submits its answer to a checker
that sends it back if something doesn't add up.

## The ground rule: don't pretend to know

This output feeds accounting, so a confident wrong value is worse than an honest "not sure". The one
rule the whole project is built on: **the output must never look like it knows something it doesn't.**
In practice that means:

- **Only catalog items.** The model picks from the SKU list; it can't invent items. Anything the form
  says isn't sold (e.g. services delivered by a partner) stays out.
- **Every amount has to be in the document.** An amount is rejected unless it's printed in the PDF or
  is the result of arithmetic on printed numbers, done through a `compute` tool rather than in the
  model's head.
- **Every date has to be in the document too.** A date must be printed in the PDF in some format, or be
  calculated from a printed date (e.g. end date = start date + term), with the calculation recorded next
  to it and re-checked. Otherwise the model is sent back to look again.
- **Ambiguity is shown, not resolved by guessing.** When the document supports more than one reading,
  the field is either left empty with the candidate readings listed, or given with `ambiguous: true`
  and the alternatives right next to the value. Nothing downstream can read that field without also
  seeing the doubt.
- **"Likely" is not "known".** A reading only gets ruled out if it contradicts something else in the
  document. If one reading is just more plausible, that's recorded as a hint, and the field stays
  flagged.
- **Missing stays missing, and says so.** If a field isn't in the document, it's left empty. I didn't
  fill it with the most common value from the ground truth, even where that would have scored better.
  If an important field is empty (a total, quantity, currency, service date, effective date or
  signature date), the form is marked `needs_review` and the field gets a note saying why it's empty.
- **Every value comes with the quote it was read from**, so anyone can check it.

## Results

Measured on the 50 synthetic order forms in `synthetic_order_form_dataset_50/` (`runs/v0.8`, $8.40 total, about
30 seconds per form). All 50 passed the checker on the first try. One form (of-0032, below) is marked
`needs_review` because its effective date is ambiguous.

**Finding the right items:** 132 of 132 contract items found, no extra items. That includes 20 forms
where a catalog item that isn't sold has a very similar name to one that is.

**Fields**, per item (132 items, 50 forms for the header fields). Each answer lands in exactly one
column, so nothing flagged is counted in the "correct" column:

| Field | Answered, correct | Answered, flagged ambiguous | Left empty (ambiguous) | Wrong |
|---|---|---|---|---|
| Currency, total, quantity, unit price | 132 | - | - | - |
| Service start / end date | 132 | - | - | - |
| Payment terms | 132 | - | - | - |
| Invoicing frequency | 104 | 28 | - | - |
| Effective date | 49 | - | 1 | - |
| Buyer / seller signature dates | 50 | - | - | - |
| Invoicing schedule type | - | - | - | 132 (left empty, not in the documents) |
| Special notes | - | - | - | 132 (doesn't match the ground truth) |

What's behind the flagged and empty cells:

- **Invoicing frequency (28 flagged):** these items have one price covering exactly 12 months. That's
  one invoice, but "one-time" and "yearly" both describe it, and nothing in the document settles which.
  The output says "one-time" and flags "yearly" as the alternative. The ground truth says "one-time" for
  19 of them and "yearly" for 9, so the dataset itself doesn't agree on a single rule. If you only
  count a flagged answer as right when it matches the ground truth, frequency is 93.2%.
- **Effective date (1 empty):** one form prints `06/04/2024` and nothing else in it tells you whether
  that's June 4 or April 6. The parser leaves it empty and notes June 4 as the likely reading, since the
  form was signed June 7. June 4 is the right answer, but we don't count it, because the output didn't
  commit to it. That's 98% if you count the empty one as wrong.
- **Invoicing schedule type:** the forms never say whether billing is upfront, recurring, hybrid etc.;
  the ground truth has values anyway. The parser leaves it empty rather than guess.
- **Special notes:** the parser picks up the form's "Up to Customer Employee Size" line, the same kind
  of note as the example ("Up to 25,000 employee size"). The ground truth has unrelated phrases
  that aren't tied to anything in the form.

### Read the 100%s with care

- **There's no held-out set.** I developed on these same 50 forms, so these numbers are optimistic.
- **The forms all come from one template** with a clean text layer. Getting amounts and dates right on
  that is a much easier test than real order forms from different vendors.
- **Some fixes came from looking at failures on this data.** Each one is written up in `CHANGELOG.md`
  with the reason it's general. The main ones:
  - Using a printed Qty column even where a SKU's parsing instruction said to leave quantity empty (v0.3).
    That was a judgement call about what the instruction meant. It also happened to match the ground
    truth, and I'd rather say that than leave it out.
  - Flagging the one-time/yearly case as ambiguous (v0.3). This *lowered* the score at the time, from
    90.2% to 78.8%, because a guess that was right some of the time became an honest flag.
  - Testing each reading of a date like `12/09/2022` against the rest of the document before calling it
    ambiguous (v0.6).
- **What I checked to avoid fitting the template:** no headings, labels or sentences from these PDFs
  appear in the code or prompts; number parsing handles other formats (`1.234,56`, `1 234,56`); scanned
  PDFs are handled, with a note that their amounts couldn't be checked against text. The grader was
  also tested, and a bug that let 1-cent errors pass was fixed before the final run.
- **The real example form** (`edge_cases/example_order_form_redacted/`) hasn't been run yet,
  because the PDF wasn't in the materials I had. The catalog and expected answer are there, ready.

The full breakdown with every failure is in `runs/v0.8/eval.md`.

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

# re-check a saved run with the current checker (no API calls)
.venv/bin/python replay.py runs/mine

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
    left empty, a date that isn't printed in the document and isn't a checked calculation from one.
- **`ofparser/postprocess.py`**: turns the accepted submission into the final output. The main job is
  invoicing frequency: use it if the document states it, otherwise infer it from how the price
  is split (e.g. four quarterly prices -> quarterly), and mark it ambiguous when two labels fit. It also
  notes every empty important field and sets `needs_review` for it.
- **`ofparser/schema.py`**: the output structure (Pydantic models).
- **`ofparser/compute.py`**: the arithmetic behind the `compute` tool.
- **`eval.py`**: scores a run against the ground truth. It matches items by SKU, compares fields
  exactly, and reports ambiguous answers separately so they don't inflate the main numbers.
- **`replay.py`**: runs a saved run's transcripts through the current checker, to see what a code
  change would flag without paying for a new run.

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
next to it. An empty important field also gets an entry in `missing_fields` saying why (ambiguous, or
not found, with the model's reason if it gave one), and a calculated date shows its calculation under
`inferred_dates`. Either way the output never looks more certain than it is.
