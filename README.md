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

The real example form is covered below, under "Testing the decisions on a real form".

### Read the 100%s with care

- **There's no held-out set.** I developed on these same 50 forms, so these numbers are optimistic.
- **The forms all come from one template** with a clean text layer. Getting amounts and dates right on
  that is a much easier test than real order forms from different vendors.
- **Some fixes came from looking at failures on this data.** Each one is written up in `CHANGELOG.md`
  with the reason it's general. The main ones:
  - Using a printed Qty column even where a SKU's parsing instruction said to leave quantity empty (v0.3,
    see "Decisions I made"). It also happened to match the ground truth, which is worth saying since it
    was a judgement call.
  - Flagging the one-time/yearly case as ambiguous (v0.3). This *lowered* the score at the time, from
    90.2% to 78.8%, because a guess that was right some of the time became an honest flag.
  - Testing each reading of a date like `12/09/2022` against the rest of the document before calling it
    ambiguous (v0.6).

The full breakdown with every failure is in `runs/v0.8/eval.md`.

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
- **`ofparser/pages.py`**: only for documents over 30 pages. Scores each page, builds the outline the agent
  starts from, and serves the `search_document` and `read_pages` tools.
- **`ofparser/catalog.py`**: loads the catalog and, for catalogs over 200 SKUs, serves the `search_catalog`
  tool.
- **`ofparser/schema.py`**: the output structure (Pydantic models).
- **`ofparser/compute.py`**: the arithmetic behind the `compute` tool.
- **`eval.py`**: scores a run against the ground truth. It matches items by SKU, compares fields
  exactly, and reports ambiguous answers separately so they don't inflate the main numbers.
- **`replay.py`**: runs a saved run's transcripts through the current checker, to see what a code
  change would flag without paying for a new run.

## Output

Each form gives an `order_form` block (parties, effective date, signature dates, grand total) and a
list of `contract_items` with the fields (`sku_code.value` is the `sku_reference`).
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
      "sku_code": {
        "value": "TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON",
        "ambiguous": false,
        "alternatives": [],
        "reason": null
      },
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
`ambiguous_fields`, or, for invoicing frequency and the SKU, given with `ambiguous: true` and the
alternatives next to it (a contract item always needs a SKU, so the likelier one is kept and the form is
marked `needs_review`). An empty important field also gets an entry in `missing_fields` saying why (ambiguous, or
not found, with the model's reason if it gave one), and a calculated date shows its calculation under
`inferred_dates`. Either way the output never looks more certain than it is.

## Decisions I made

The code was written with Claude Code, but the decisions below were mine. Most came from looking at
the failures in a run and deciding what the right behaviour was, not just what would score better.

**Only general fixes.** Every change had to make sense for order forms in general, not only for this
template. No headings, labels or sentences from the synthetic PDFs appear in the code or prompts, and
nothing is filled in from patterns in the ground truth. If a fix only worked because of how these 50
forms happen to look, it didn't go in.

**No hallucination, even at the cost of accuracy.** For accounting data, a wrong value that looks right
is the worst possible outcome. The system never fills a field just to score better, and where something
can't be read from the document, the output says so plainly. That's why invoicing schedule type stays
at 0%: the forms don't state it, so the parser doesn't guess.

**A printed quantity overrides the catalog's "leave it null" rule.** After the first run, 4 quantities
were wrong. The catalog's instruction for that SKU said to record a quantity only when minimum and
maximum monthly hours are given, and otherwise leave it null. It didn't cover forms that simply print
a Qty column. A null quantity also breaks the invoicing frequency calculation, which needs quantity x
unit price. So I decided that a quantity printed in the document counts as stated, and the catalog's
null rule only applies when the document gives none.

**Two kinds of ambiguity, handled differently.**
- When the document could mean different things (`06/04/2024` could be June 4 or April 6), the field
  is left empty. The possible readings are listed, and the likelier one is marked if the context
  favours it.
- When the facts are clear but more than one label describes them correctly (a single price for a
  12-month term is both "one-time" and "yearly"), the value is given and flagged ambiguous, with the
  other correct option next to it.

In both cases the accountant sees the options right away instead of working them out from the PDF.

**Auditing for cases the dataset doesn't cover.** Once all the tests were passing, I asked for a review
of the whole codebase, aimed at inputs these 50 forms don't contain. It turned up four problems, all
fixed:
- **The grader forgave 1-cent errors** on money fields. Amounts now have to match exactly, to the cent.
  Re-scoring the earlier runs showed no reported result had been inflated by it.
- **The checker let blank values through without raising anything.** Now a blank important field sends
  the model back to look for it in the document. If it's still blank, the form is flagged for review
  with a note on that field saying why. Fields that are blank by design (schedule type, special notes)
  aren't flagged, so a review flag always means something.
- **European and other number formats would have been rejected.** The checker only understood
  `1,234.56`, so a form written as `1.234,56`, `1 234,56` or `1'234.56` would have had every amount
  treated as "not in the document". It now recognises all of these.
- **Scanned PDFs weren't supported.** A PDF with no text layer would have failed every check. Now it's
  detected: the model reads the page images instead, and the output carries a note that the amounts
  couldn't be checked against the document text.

## Testing the decisions on a real form

The example is a real (redacted) order form with a different layout and a different 5-SKU
catalog. I ran it with no code changes (`runs/example`, $0.32). The 3 expected items were found and
nothing else, and every amount, date, schedule type and frequency matches the expected answer.

| On the real form | Decision behind it |
|---|---|
| Worked on a new layout and catalog with no changes | Only general fixes |
| Services delivered by a partner were left out | Only items the form actually sells |
| Redacted customer name left empty, not guessed | No hallucination |
| No effective date printed: the model was sent back to look, confirmed it's not there, and the form is marked for review | Blank checker |
| "Invoices are sent Annually" was used as the frequency | Stated billing wins |

Two small differences: payment terms are quoted in full ("Net 55 from the date of the invoice" vs
"Net 55"), and a note printed once at the top of the form ("Up to Customer Employee Size: 25,000") went
on all 3 items instead of just the platform licence.

## Long documents

The forms above are a few pages. Real contracts can bury the order form in hundreds of pages of legal terms,
and sending all of it doesn't work: a 1,000-page PDF is about 4 million tokens, over the API's 600-page limit,
and would cost around $25 per turn even if it fit.

So for anything over 30 pages, the agent doesn't get the document up front. It gets a short outline built by
plain code (headings and page numbers, about 30 lines for 1,000 pages), with hints on which pages look like
prices or signatures. It reads the pages it needs with `read_pages` and can search the whole text with
`search_document`. The checker still checks every amount and date against the full document, so seeing only
some pages never weakens it.

To test it, I generated long contracts with decoy pages (a price list of optional services using catalog
product names, SLA tables, date-heavy logs, a table of contents) and buried a real form inside. One
version splits the form apart, with the term, pricing, invoicing and signatures hundreds of pages from each
other, and adds an amendment that changes a price.

| Document | Pages it read | Found every page it needed | Cost | Items correct |
|---|---|---|---|---|
| 1,000 pages, form in the middle | 7 | yes | $0.46 | yes |
| 1,000 pages, form at the start / end | 11 / 9 | yes | $0.68 / $0.54 | yes |
| 200 / 500 pages | 7 / 15 | yes | $0.46 / $0.74 | yes |
| 1,000 pages, form scattered + amendment | 12 | yes (5 of 5) | $0.72 | yes, with the amended price |

The optional products on the decoy price list were left out every time. Caveats: one run per document, and
the documents are generated, so real long contracts may be laid out in ways the outline handles less well.
Long scanned PDFs can't be outlined yet. Details are in `CHANGELOG.md` (v0.9, v0.10) and
`edge_cases/long_document/`.

## Large catalogs

Catalogs up to 200 SKUs go into the prompt; above that, the agent looks products up with a `search_catalog`
tool that tolerates abbreviations, OCR errors and typos, and returns the closest SKUs plus their look-alikes.
Tested on a generated 2,000-SKU catalog (the real 21 plus editions, add-ons, regional and near-name variants):
both ways got every SKU right on the forms tried. Caching keeps the full catalog affordable inline at 2,000 SKUs
(the first form pays to cache its 230K tokens, about $1.65, and later forms cost about $0.35 each), but at
roughly 115 tokens per SKU a catalog of 5,000-10,000+ SKUs no longer fits in the model's context at all.
Retrieval is what scales past that, and at 2,000 SKUs it already cost about the same as the 21-SKU setup
($0.20 vs $0.17 per form). One form, of-0044, came out differently from earlier runs: its effective date
"03/01/2024" was left blank as ambiguous (with March 1 as likely, which is correct) where earlier runs answered
it; both readings fit the document, so this is run-to-run variation, not the catalog. Details in `CHANGELOG.md`
(v0.11) and `edge_cases/big_catalog/`.

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

# long-document test case: build the PDFs, run them, report recall and correctness
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python scripts/make_long_doc.py
.venv/bin/python parse.py --catalog edge_cases/example_order_form_redacted/catalog.json \
    edge_cases/long_document/generated/*.pdf --out runs/long
.venv/bin/python scripts/long_doc_report.py runs/long

# tests (no API calls)
.venv/bin/python -m unittest discover -s tests -t .
```

Each run folder gets `outputs/<form>.json` (the extraction), `transcripts/<form>.json` (the full
conversation with the model, useful for seeing why it chose something) and `run_meta.json`.
