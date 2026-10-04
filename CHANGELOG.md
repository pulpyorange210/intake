# Changelog

Each entry records what changed, which observed failure motivated it, and why the change is general
(not fitted to the synthetic dataset). Results are measured on the same 50 synthetic forms we iterate on,
so they are optimistic; the rule is that no change may depend on phrasing or layout specific to that template.

## v0.1 - initial system (2026-09-24)

**What**
- Agent loop over the Claude API (`claude-opus-5`, adaptive thinking): the model gets the PDF as a
  document block plus the `pdftotext -layout` text layer, the full SKU catalog (with parsing instructions)
  in the system prompt, and two tools: `compute` (exact decimal arithmetic) and `submit_extraction`.
- Validator on every submission:
  - Hard errors (must fix): schema, SKU not in catalog, amount not grounded (not printed in the PDF and
    not a compute result from document values), invalid ISO date, start after end, bad currency code.
  - Warnings (fix or override with a written reason): `price_ratio_not_integer` (total / (qty x unit) is
    not a whole number of periods), `period_mismatch` (period length not 1/3/6/12 months), `period_amounts_sum`,
    `grand_total_mismatch` (only if the model found a grand total, whatever its label), `excluded_conflict`
    (SKU appears in the model's own list of explicitly excluded SKUs), `evidence_not_found`.
  - Max 3 submissions, then output is returned with `needs_review: true` and the unresolved issues.
- Post-processing: invoicing frequency is taken from explicit billing text when the model finds it
  (`invoicing_frequency_source: stated`); otherwise inferred from the pricing period
  (`inferred_from_pricing`), with a single price covering the whole term treated as one invoice (one-time).
- Evidence quotes for every non-null field; full agent transcripts saved per form.

**Deliberately not done**
- No template phrases in prompt or code (e.g. no "TOTAL SUBSCRIPTION", no "not sold in this order").
  The not-sold statement is only used via the model's generic `explicitly_excluded_skus` list, and only
  as a warning - it never removes a priced line.
- No defaults learned from the ground truth (e.g. most common invoicing type).

**Results** (run `runs/v0.1`, 50 forms, $11.05, ~50 s/form):
- Item detection: precision 100%, recall 100% (132/132, 0 extra). Near-twin forms (a non-sold catalog
  name overlaps a sold one, detected automatically by eval): 20 forms, 100% / 100%.
- Header: effective date, buyer and seller signature dates all 100%.
- Item fields: currency, total, unit price, start/end dates, payment terms 100%; quantity 97.0%;
  invoicing frequency 90.2% (all inferred - no form states it); invoicing schedule type 0%;
  special notes 0%.
- 0 forms flagged needs_review. 44/50 forms needed a 2nd submission, 4 needed a 3rd.

**Failure analysis**
- quantity (4 misses): all PREMIUM_SUPPORT. The catalog instruction says "If minimum/maximum monthly
  hours are specified, capture them; otherwise leave quantity null", and the model followed it; ground
  truth uses the printed Qty column (1 or 3). Instruction/ground-truth conflict - left as-is pending a
  decision. The same 4 items account for 4 of the 13 frequency misses (no quantity -> no ratio).
- invoicing_frequency (other 9 misses): 12-month single-price items where ground truth says yearly and
  the fallback says one-time; both mean one invoice and nothing in the document distinguishes them.
- invoicing_schedule_type / special_notes: not present in the PDFs. The model returned null for schedule
  type (2 items said "upfront", from "invoices are sent in advance"), and put the form's
  "Up to Customer Employee Size" in special_notes on 47 items - consistent with the real example form's note
  ("Up to 25,000 employee size"), but not with this ground truth, whose notes are unrelated phrases.
- Extra submissions: every bounce was `evidence_not_found`, never a value problem. Values were identical
  between first valid and final submission on all 50 forms. Causes: (a) the model joins non-adjacent
  text (party name + signature date) with "..."; (b) pdftotext -layout splits wrapped cells
  ("Talent Intel. Platf. Prem. Ed." / "(Add-on)") around the numbers, so a faithful visual quote can't
  match. 4 forms also wrapped the submission in an extra {"submission": ...} object (schema error).

## v0.2 - cheaper validation loop (2026-09-24)

**What**
- Quotes may join non-contiguous fragments with "..."; each fragment must appear in order.
  General: signature blocks and wrapped table cells are non-contiguous in any layout.
- `evidence_not_found` is now a non-blocking review note (`review_notes` in the output), not a warning
  sent back to the agent. General: quote matching is inherently brittle against extracted text layers,
  and the checks that protect values (amount grounding, SKU in catalog, dates) are independent of it.
- Submit tool description says to pass fields at the top level (fixes the wrapper schema error).
- Tried and rejected: also matching quotes against pdftotext's non-layout text - recovered 1 of 66
  unmatched quotes.

**Expected impact** (replaying v0.1's first valid submissions through the new validator, no API cost):
50/50 accepted on the first valid submission, with values identical to v0.1's final outputs - so the same
accuracy at roughly one fewer model turn per form. To be confirmed with a live run.

## v0.3 - stated quantities, and abstain when ambiguous (2026-09-24)

**What**
- A quantity printed in the document (e.g. a Qty column) counts as a stated quantity. SKU parsing
  instructions about leaving quantity null apply only when the document states no quantity.
  Motivation: the 4 PREMIUM_SUPPORT quantity misses in v0.1 (instruction said null, form printed Qty 1/3).
  Decision made by me as the more defensible reading of the instruction, not to match
  the ground truth.
- New rule (non-negotiable): when the document supports more than one correct reading, the system says so
  instead of guessing. The field is left null and recorded in `ambiguous_fields` with the candidate
  readings and the reason.
  - Model side: new `ambiguities` list in the submission; the prompt tells the model to use it for
    conflicting or equally valid readings (not for merely missing information).
  - Frequency fallback: a single price covering a term that is itself exactly one standard period
    (1, 3, 6 or 12 months) fits both "one-time" and that periodic label, so it is marked ambiguous.
    A single price covering a multi-year term stays "one-time"; several periods of a standard length
    stay monthly/quarterly/biannually/yearly.
- Eval reports abstentions separately: accuracy (abstentions count as wrong), answered accuracy
  (abstentions excluded), and the abstention count.

**Expected impact**: on ground truth values, the frequency fallback now decides 104/132 items, all
correct, and abstains on 28 (the one-time vs yearly cases). v0.2 and v0.3 are measured together in
`runs/v0.3`.

**Results v0.2 + v0.3** (run `runs/v0.3`, 50 forms, $8.11 vs $11.05, 50/50 accepted on the first submission):
- Item detection 100% / 100%; near-twin forms 20, 100% / 100%.
- currency, total, quantity (was 97.0%), unit price, dates, payment terms: 100%.
- invoicing_frequency: 104 answered, all correct (100% answered accuracy); 28 abstained as ambiguous
  (one-time vs yearly). Strict accuracy 78.8% (was 90.2% when guessing "one-time").
- Header: signature dates 100%; effective_date 98% - of-0032 prints "06/04/2024" and the model abstained
  (candidates 2024-06-04 / 2024-04-06: the document has no other numeric dates to establish MM/DD vs
  DD/MM, and both readings fit the signature and start dates). Correct behavior under the ambiguity rule.
- invoicing_schedule_type: inconsistent from identical boilerplate ("Invoices are sent in advance in
  accordance with each line item's billing frequency"): null on most forms, "upfront" on 3,
  "recurring" on 1, flagged ambiguous on 1. special_notes: still the employee-size line.

## v0.4 - consistency fixes (2026-09-24)

**What**
- Prompt: billing "in advance"/"in arrears" describes timing within a period, not schedule type or
  frequency. General billing semantics; fixes the inconsistent schedule types above.
- Validator hard error `bad_ambiguity`: an ambiguity entry must name an existing field at its level
  (item fields need the item's index) and that field must be null. Motivation: of-0011 put an item's
  invoicing_frequency ambiguity on the order form header.

**Results** (targeted rerun of the 6 affected forms, `runs/v0.4-check`, $0.89): invoicing_schedule_type
is null on all 6; no misplaced ambiguity entries. Removes the one accidental schedule-type match
(of-0018) - accepted, since it came from text that doesn't support it.

## v0.5 - ambiguity shown next to the value, with hints (2026-09-24)

The principle behind the ambiguity rule, as clarified by me: the output must never look
like it knows something it doesn't. Giving a value is fine if the uncertainty is impossible to miss.

**What**
- `invoicing_frequency` is now always a block: `{value, source, ambiguous, alternatives, reason}`.
  Always a block (not only when ambiguous) so downstream code sees one type. The flag sits next to the
  value, so anything reading only that field still sees the ambiguity.
  - `source`: `stated` (explicit billing text), `inferred_from_pricing` (fallback), or
    `document_ambiguous` (the model found conflicting readings; value null).
  - The 12-month single-price case now gives `value: "one-time"` with `ambiguous: true`,
    `alternatives: ["yearly"]`, and a reason stating the fact: one invoice for the full amount over the
    term. v0.3 returned null, which threw away the known fact (one invoice) because the label was
    unclear. "one-time" is the primary label because a single price covering the whole term is one
    invoice for the whole term - the same rule that labels 24/36-month single-price items one-time.
- Ambiguity entries (model side) can carry `likely` + `likely_reason`: when context favours one
  candidate (e.g. of-0032's 06/04/2024 effective date is 3 days before the 07 Jun 2024 signature), the
  hint is recorded. The field itself stays null. Validator: `likely` must be one of the candidates.
- Other fields stay plain values; when ambiguous they are null, with candidates/likely/reason in the
  item's `ambiguous_fields`.
- Eval splits every field into unflagged answers, flagged-ambiguous answers, and abstentions, so flagged
  answers are never blended into the headline accuracy.

**Expected impact** (ground truth replay): invoicing_frequency 104 unflagged (all correct) + 28 flagged
(19 match the ground-truth label, 9 don't - both labels are valid for those items).

**Results** (run `runs/v0.5`, 50 forms, $8.14, 49/50 accepted on the first submission):
- Item detection 100% / 100%; near-twin forms 20, 100% / 100%. Currency, totals, quantity, unit price,
  end date, payment terms, signature dates: 100%. invoicing_schedule_type: null everywhere (0%).
- invoicing_frequency: 101/104 unflagged correct (the 3 misses are null, see of-0048 below);
  28 flagged ambiguous (one-time, alternative yearly), of which 19 match the ground-truth label.
- effective_date: of-0032 abstained again, now with `likely: 2024-06-04` ("consistent with the
  07 Jun 2024 signature") - as intended.
- New: of-0048 prints the start date as "12/09/2022" and the model abstained on service_start_date
  for all 3 items (candidates 2022-12-09 / 2022-09-12, likely Dec 9). In v0.3 it answered Dec 9
  unflagged - run-to-run variation. But Sep 12 is not actually a valid reading: it gives a 453-day term
  in which the 4 billing periods implied by the prices would be 3.75 months each, and it starts before
  the 10 Nov effective date. Abstaining here overstates the ambiguity. The null start date also left
  those 3 items without a frequency.
- The one retry: of-0048's first submission used a descriptive field name in an ambiguity entry;
  `bad_ambiguity` caught it and the model fixed it.

## v0.6 - contradictions eliminate readings, plausibility only hints (2026-09-24)

**What**
- Prompt: before calling a field ambiguous, test each candidate reading against the rest of the
  document (price/quantity/term arithmetic, other dates). A reading that contradicts the document is not
  valid; if exactly one survives, use it and quote the deciding evidence. Closeness or typicality never
  eliminates a reading, it can only make one `likely`.
  Motivation: of-0048 (above). General: "multiple correct answers" means multiple readings consistent
  with the document, not multiple ways to parse a string.

**Results** (targeted rerun, `runs/v0.6-check`, $0.33):
- of-0048: service_start_date 2022-12-09 on all 3 items, unflagged; frequency back to quarterly (correct).
- of-0032: effective_date still abstained with likely 2024-06-04 - nothing in that document depends on
  the effective date, so April 6 is not contradicted. Correct distinction.
- Known gap: of-0048's evidence quotes only "Start Date: 12/09/2022", not the consistency check that
  decided it, so the output doesn't show that a format question was resolved. Follow-up candidate.
- Not yet measured on the full 50; will be covered by the final full run before the README.

## v0.7 - offline audit: tests, grader fix, checker gaps (2026-09-24)

No API calls. Run the tests with `python -m unittest discover -s tests -t .` (21 tests, ~3 s).

**1. Grader tests** (`tests/test_eval.py`)
- Ground truth scored as a prediction -> 100% on every field, P/R 100%, 50/50 forms fully correct.
- **Bug found:** a one-cent change to a unit price was scored as correct. Money fields were compared
  with `abs(pred - gold) <= 0.01`, i.e. a 1-cent tolerance. Fixed: exact comparison at the cent.
  Re-scored v0.1, v0.3 and v0.5 with the fix: totals and unit prices remain 100% - no earlier claim was
  inflated by the bug.
- Also tested: a wrong SKU counts as one extra + one missed item; an abstention lands in the abstained
  column, not in unflagged accuracy.
- `eval.py` refactored into `score_run()` so it can be tested; CLI unchanged.

**2. Checker tests** (`tests/test_validator.py`)
- Caught as hard errors: a planted amount not in the PDF (`ungrounded_amount`), a SKU not in the
  catalog, reversed dates, a malformed ambiguity entry. Caught as warnings: a line whose unit price is
  a real document number from another line (`price_ratio_not_integer`), a not-sold SKU conflict.
  Overrides silence warnings but never hard errors. All 50 ground-truth forms pass with no issues.
- **Gap found - why v0.1's null quantities weren't flagged:** with quantity null, `price_ratio` returned
  None and every ratio check was silently skipped, and no check required quantity at all. Fixed: new
  `missing_value` warning when currency, total, quantity or service dates are null without an ambiguity
  entry. It is a warning, so a SKU instruction that genuinely requires null can be honoured via an
  override with that reason. Replaying all accepted v0.5 submissions: no new warnings.

**3. Code audit**
- (a) Signatures: matched by party name - the prompt says to attribute each date to the party named in
  its signature block; no position logic exists anywhere in code or prompt. OK.
- (b) Stated billing wins: `build_output` uses a stated `invoicing_frequency` before any price math;
  tested with a monthly-priced item "billed annually" -> yearly/stated. OK.
- (c) No phrases copied from these PDFs in code or prompts (searched for the template's headings, total
  labels, not-sold sentence, billing boilerplate, party/product names). Only "e.g. a Qty column" -
  a generic table term. OK.
- (d) 6-month billing: allowed in the schema (`biannually`, `half_year`), the sensible-period check and
  the fallback; tested (2 periods/year -> biannually, single price over 6 months -> flagged with
  alternative biannually). OK.
- (e) Layout assumptions - **two found and fixed:**
  - Number grounding only understood `1,234.56`. A `1.234,56` / `1 234,56` / `1'234.56` document would
    have had every amount rejected as ungrounded. Now every notation is recognised (each token read under
    every notation it fits, since the locale is unknown).
  - A scanned PDF (no text layer) would have failed grounding on every amount. Now detected: the model is
    told to read the page images, grounding and quote checks are skipped, and the output carries a
    `no_text_layer` review note saying amounts could not be checked against document text.

**Final results** (run `runs/v0.7`, full 50 forms on the committed v0.7 code, $8.18, ~70 s/form with
6 in parallel, 50/50 accepted on the first submission, 0 needs_review, 0 overrides):
- Item detection: precision 100%, recall 100% (132/132); near-twin forms 20, 100% / 100%.
- Currency, total, quantity, unit price, service start and end dates, payment terms: 100% (exact to
  the cent for money).
- invoicing_frequency: 104/104 unflagged correct; 28 flagged ambiguous ("one-time", alternative
  "yearly"), 19 of which match the ground-truth label.
- Header: signature dates 100%; effective date 49/49 answered correct + 1 abstained (of-0032, likely
  2024-06-04, which is the ground-truth value).
- of-0048 (12/09/2022): start date answered correctly, unflagged - the v0.6 fix holds.
- invoicing_schedule_type and special_notes: 0% - neither is present in the PDFs.
- 65 non-blocking `evidence_not_found` review notes (quotes of wrapped rows / side-by-side blocks).

## v0.8 - flag important blanks, catch dates not printed in the document (2026-09-25)

**What**
- Important blanks are flagged. A blank currency, total, quantity, service date, effective date or
  signature date sets `needs_review: true` and gets a `missing_fields` entry on that field (status
  `ambiguous` or `not_found`, with the ambiguity reason or the model's override reason, or "no reason
  given"). This applies even when the model explained the blank. Motivation: an overridden
  `missing_value` warning used to give a clean-looking output with an empty total. Not flagged: fields
  blank by design (invoicing schedule type, special notes) and the one-time/yearly frequencies, which
  have a value with the ambiguity next to it.
- The `missing_value` warning now also covers the three header dates (they were not checked at all).
- Dates are grounded like amounts. Every date must be printed in the PDF in some common format
  (ISO, numeric with / - ., "Aug 08, 2025", "8th of August 2025", "12-Dec-2023", ...), matched on the
  value, not the quote. A numeric date whose day and month can swap (06/04/2024) counts as present
  for both readings; choosing between them stays with the ambiguity rule. A date that is not printed
  needs an `inferred_dates` entry (a printed `from_date` plus `add_months` / `add_days` and an
  explanation), which the checker recomputes. Otherwise `date_not_in_document` goes back to the model.
  Motivation: a date with no source only produced a non-blocking `evidence_not_found` note, so a
  plausible made-up date could pass. An overridden `date_not_in_document` also sets `needs_review`.
  Skipped for scanned PDFs, like amount grounding.
- `replay.py`: re-runs a saved run's transcripts (compute calls and submissions, in order) through the
  current checker and post-processing, no API calls.
- 17 new tests (38 total).

**Replay of v0.7 before the live run** (no API cost): only of-0032 is flagged `needs_review` (its
ambiguous effective date); 0 date warnings; no other issues on any final submission. All 50
ground-truth submissions also pass the new date check, so every true date is printed in its PDF.

**Results** (run `runs/v0.8`, full 50 forms on commit `34a7e1e`, $8.40, ~28 s/form with 6 in parallel,
50/50 accepted on the first submission, 0 overrides, 0 inferred dates):
- Every field score is identical to v0.7: item detection 100% / 100%; currency, total, quantity, unit
  price, service dates, payment terms 100%; invoicing_frequency 104/104 unflagged + 28 flagged;
  effective date 49/49 + 1 abstention (of-0032, likely 2024-06-04); signature dates 100%;
  schedule type and special notes 0%.
- needs_review: 1 form (of-0032, effective date ambiguous), was 0 in v0.7. This is the intended change:
  the blank was always there, it is now impossible to miss.
- 63 non-blocking `evidence_not_found` notes (65 in v0.7).

## Real example form (2026-09-25)

The `example_order_form_redacted.pdf` arrived after v0.8 and was run with no code changes
(`runs/example`, 5-SKU catalog, $0.32, 2 submissions).
- 3/3 expected items, 0 extra; SKU-004 (implementation via a partner) listed in explicitly_excluded_skus.
- Totals, unit prices, quantity, currency, dates, schedule type (recurring) and frequency (yearly,
  source `stated`) match the expected answer. First real test of stated billing: every synthetic form
  left billing unstated.
- Differs from the expected answer: payment terms "Net 55 from the date of the invoice" (expected
  "Net 55"); the form-level "Up to Customer Employee Size: 25,000" note is on all 3 items (expected
  only on SKU-001). Not tuned for: one example, and which items a form-level note covers is a
  judgement call.
- First live exercise of the v0.8 blank handling: the form states no effective date; submission 1 was
  sent back with `missing_value`, the model overrode it with the reason, and the output is marked
  `needs_review` with that reason in `missing_fields`.

## v0.9 - long documents: page selection with search and read tools (2026-10-04)

**Test data** (`scripts/make_long_doc.py`, seeded, byte-for-byte reproducible): the real 5-page example form
inserted unchanged into contract boilerplate, with decoy pages (table of contents pointing to the form,
an optional-services rate card using catalog product names, SLA tables, date-dense amendment logs, dollar
amounts in ordinary clauses). Variants: form at page 412 / 3 / 990 of 1,000 pages, at 82 of 200, at 206 of 500.
Expected output is the example's `expected.json`.

**Baseline** (`scripts/count_full_doc.py`, token-counting API, nothing run): the current approach sends the whole
PDF plus its whole text layer.

| Document | Pages | First-turn input tokens | Cost of that turn | Possible? |
|---|---|---|---|---|
| example form | 5 | 19K | $0.12 | yes |
| n200_at82 | 200 | 795K | $4.97 | yes, just under the 1M context |
| n500_at206 | 500 | 2.0M | $12.54 | no: over the 1M-token context |
| n1000_at412 | 1000 | 4.0M | $25.22 | no: over the API's 600-page limit |

**What** (`ofparser/pages.py`; only for documents over 30 pages, shorter ones are sent whole as before)
- Every page is indexed with plain code and scored on generic signals: currency amounts, table-like rows,
  dates, billing words (qty, total, term, invoice, ...) and the catalog's own product names.
- Sent first: the best page and any page scoring at least 35% of it (up to 6), each with its neighbours, the
  first 2 pages, and up to 3 pages with signature cues; at most 20 pages. The model gets those pages as a PDF
  plus their text, labelled with their page numbers in the full document.
- Two new tools: `search_document(query)` over every page's text, and `read_pages(first, last)` returning up to
  10 pages as PDF plus text (tool results can carry PDF pages, checked with a live call).
- The checker still grounds amounts and dates against the whole document's text. When only part of the
  document was shown, the grand-total mismatch and missing-value warnings tell the model to search further.
- Up to 24 turns for long documents (12 otherwise). Output `meta.long_document` records pages sent, pages read
  and searches.
- Tried and changed: a "keep at least 3 top pages" rule let a near-zero page in as a top page (caught by a unit
  test); replaced by the relative cutoff.
- 10 new tests (48 total). A live check on of-0001 gave the same values as v0.8 through the unchanged short path.

**Results** (`runs/long_doc/report.md`, $3.19 for all 5):

| Variant | Pages sent | Read later | Input tokens (all turns) | Cost | Time | 3 items correct |
|---|---|---|---|---|---|---|
| n1000_at412 | 11 | 5 | 295K | $0.47 | 80 s | yes |
| n1000_at3 | 10 | 5 | 316K | $0.68 | 70 s | yes |
| n1000_at990 | 11 | 5 | 355K | $0.71 | 63 s | yes |
| n200_at82 | 11 | 6 | 312K | $0.71 | 70 s | yes |
| n500_at206 | 11 | 4 | 272K | $0.62 | 63 s | yes |

- Every variant: exactly SKU-001/002/003 with the expected totals, unit prices, quantity, currency, dates,
  schedule type and frequency. SKU-004 and SKU-005 listed as explicitly excluded (the rate-card decoy offers
  them as optional, not purchased).
- Cost tracks the pages read, not the document's length: the 1,000-page variants cost about the same as the
  200-page one, roughly twice the 5-page form on its own ($0.32).
- In every run the model read the rest of the form (its product-description pages) with `read_pages`, and,
  after the missing-value warning, searched the whole document for an effective date before concluding there
  is none. All 5 are `needs_review` for that blank effective date, as with the 5-page form.
- Run-to-run variation in the two fields that already differed on the 5-page form: payment terms are "Net 55"
  in one run and "Net 55 from the date of the invoice" in four; special notes are empty in three runs and the
  employee-size line on 2 of 3 items in two.
- Limits: scanned long documents (no text layer) can't be indexed and still take the old path; the page scorer
  has only been tested on this generated boilerplate, so decoys and real long contracts may score differently.

## v0.10 - scattered form, and outline navigation for long documents (2026-10-04)

**Scattered test variant** (`n1000_scattered`): the form's first page split into three pages placed far apart
(service term p.120, pricing p.415, invoicing schedule and payment terms p.640), its signature page at p.880, and a
one-page amendment at p.955 that changes Premium Support to $45,000.00 a year (total $135,000.00; the amendment
also restates the order total as $1,125,000.00). Expected output: `edge_cases/long_document/expected_scattered.json`.
- Splitting by cropping a copy of the original page was tried first and rejected: a live check showed the model
  still reads text outside the crop ("Page 1 of 5", the PO section) even though pdftotext doesn't. The pieces are
  redrawn word by word from the original page at the original positions and sizes. Bold headings come out with
  extra spacing ("SUBSCRIPTION    SERVICE FEES") and one merged word ("Feesare"); amounts and dates are intact.
- The generator refactor leaves the earlier 5 variants byte-for-byte identical (same hash).
- `variants.json` now lists, per variant, the pages that hold information the order needs.

**Outline navigation** (`PageIndex.outline()`, now the default for documents over 30 pages; v0.9 page selection
remains as `parse.py --long-doc select`)
- Built with plain code from the text layer: running headers/footers are dropped (lines on 20%+ of pages, digits
  ignored); headings are short all-caps lines, numbered clause headings, lines starting with words like Exhibit /
  Schedule / Amendment, and title-like first lines of a page; sentence tails ("... in Exhibit G.") are not
  headings. Pages with part headings get a line; runs of pages with only numbered clauses collapse to one line.
  Page scores are tags only: [score N] on the top pages, [signatures] on pages with signature cues.
- 1,000 pages -> 25-32 outline lines (about 800 tokens). The first message is the outline only; the model then
  fetches pages with read_pages and can use search_document.
- First attempt gave 402 lines: wrapped sentence fragments ("Section 21.2.", "Exhibit G.") counted as headings,
  and a regex dropped the first letter of clause titles. Both fixed before any run.
- New general prompt rule (all documents): use values as amended by an amendment, addendum or change order, quote
  the amending text, and mention it in special_notes. Short-form check on of-0001 after the change: same values as
  v0.8.
- Output `meta.long_document` adds mode, outline_lines and pages_seen. `scripts/long_doc_report.py` reports page
  recall: of the pages needed for the order, how many the model saw (sent or read; search results don't count).
- 3 new outline tests (51 total).

**Results**

Outline mode, all 6 variants (`runs/long_doc_outline/report.md`, $3.60):

| Variant | Pages seen | Page recall | Searches | Cost | Time | Items correct |
|---|---|---|---|---|---|---|
| n1000_at412 | 7 | 2/2 | 6 | $0.46 | 70 s | yes |
| n1000_at3 | 11 | 2/2 | 9 | $0.68 | 92 s | yes |
| n1000_at990 | 9 | 2/2 | 6 | $0.54 | 77 s | yes |
| n200_at82 | 7 | 2/2 | 4 | $0.46 | 74 s | yes |
| n500_at206 | 15 | 2/2 | 3 | $0.74 | 88 s | yes |
| n1000_scattered | 12 | 5/5 | 10 | $0.72 | 113 s | yes |

- Scattered: all five pieces read, the amendment applied (SKU-003 $45,000.00 / $135,000.00, grand total
  $1,125,000.00) and noted in SKU-003's special_notes.
- For comparison, v0.9 select mode on the 5 standard variants (re-scored from `runs/long_doc`): recall 2/2 on all,
  15-17 pages seen, $0.47-0.71. Select mode on the scattered variant (`runs/long_doc_select_scattered`, $1.26):
  recall 5/5 but 29 pages seen; items, amounts and the amendment correct, but invoicing_schedule_type "upfront"
  instead of "recurring" on all 3 items, from the same "Invoices are sent Annually, in advance" sentence that the
  outline run read as recurring. A reading slip, not a navigation miss; one run each, so not evidence either
  mode reads better.
- Every run is needs_review for the blank effective date only (the form states none), as before.
- special_notes vary more in outline mode: the model reads the product-description pages and sometimes copies
  entitlements from them (e.g. SMS message allowances). Not graded; consistent with special_notes being the least
  settled field.
- Limits: one run per variant; the outline heuristics have only seen this generated boilerplate and the example
  form; scanned long documents still can't be indexed.

## v0.11 - catalog scaling: shared prompt cache, 2,000-SKU catalog, search_catalog retrieval (2026-10-04)

**1. Prompt cache across forms.** Per-turn usage is now logged (`meta.usage.per_turn`). Measured before the fix
(`runs/cache_before`, 3 forms run one after another): every form's first turn read 0 tokens from the cache and
wrote the whole ~13.5K-token prompt again, because the only cache point was at the end of the messages, after
the PDF, which differs per form. Fix: a cache point at the end of the system prompt (rules + catalog; tools render
before it, so they're included). After (`runs/cache_after`, forms not run recently): each form's first turn reads
the 8,115-token shared prefix and writes only its own PDF and text. Saving: 8,115 x (1.25 - 0.10) x $5/M = about
$0.047 per form, roughly 28% of v0.8's $0.168. A first "after" run on the same 3 forms was discarded: it read their
whole first message from the cache left by the "before" run, which overstated the saving.

**2. 2,000-SKU catalog** (`scripts/make_big_catalog.py`, seeded, reproducible; generated file gitignored): the real
21 plus look-alikes (editions, add-on vs base, regions, deployments, units, billing terms, near-name siblings) and
a wider vendor price book. Each look-alike differs from a real SKU by something a form would print. Inline, the
catalog is 220,705 tokens. "Premier Support" was generated at first and removed: the forms print "Prem. Support",
which ties Premier and Premium, so the expected answer would not be decidable from the document.

**3. search_catalog** (`ofparser/catalog.py`): token matching that folds OCR-confusable characters (0/O, 1/l/I,
5/S, 8/B), accepts abbreviations by prefix ("Platf.") or letters in order ("Mgmt"), and one-character typos;
ranked by a Dice-style overlap so unmentioned regions or editions lower a candidate's score. Returns the top 5
plus up to 3 close siblings of each, with descriptions and parsing instructions. Catalogs up to 200 SKUs stay
inline (prompt byte-for-byte unchanged); larger ones get a retrieval section and the tool
(`parse.py --catalog-mode auto|inline|retrieval`). The checker still validates codes against the full catalog.
Offline, on the 211 printed product rows of the 50 forms: correct SKU among the candidates 211/211 and ranked
first 211/211 (201/211 before removing "Premier Support"). 8 new tests (59 total).

**4. Results** (`runs/catalog_report.md`; checkpoint first: one form in each mode, then the full runs)

| Run | Forms | Items (P / R) | Retrieval recall | Fields correct | Input tokens / form | Cost / form |
|---|---|---|---|---|---|---|
| v0.8, 21 SKUs, same 10 forms | 10 | 100% / 100% | - | 174/174 | 29,611 | $0.170 |
| 2,000 SKUs inline (near-twin forms) | 10 | 100% / 100% | - | 174/174 | 534,947 | $0.511 |
| v0.8, 21 SKUs, all forms | 50 | 100% / 100% | - | 792/792 | 29,889 | $0.168 |
| 2,000 SKUs, retrieval | 50 | 100% / 100% | 132/132 | 792/792 | 57,547 | $0.196 |

- Inline: $5.11 for 10 forms run one at a time. The first form paid $1.65 (writing the 232K-token prompt to the
  cache); the other nine read it and cost $0.32-0.48 each. Run in parallel, every form would pay the write.
- Retrieval: $9.80 for 50 forms; 4.6 searches per form, 3.3 turns on average, every form accepted on the first
  submission. Queries were the printed names ("Prem. Support", "Talent Mgmt Ent."). 0 wrong SKUs; near-twin
  forms 100% / 100%.
- One difference from v0.8, not caused by the catalog: of-0044's effective date "03/01/2024" was left blank as
  ambiguous (likely 2024-03-01, correct), where v0.8 answered it unflagged. Both readings fit the document
  (signed 3 and 8 March, start 22 March), so the blank follows the ambiguity rule; run-to-run variation.
- Limits: both modes made no SKU errors, so this catalog did not find where matching breaks. The forms always
  print enough to decide (no form omits an edition or region that a look-alike adds), and abbreviations are mild.
  Harder cases (forms naming a product family only, unseen abbreviations, two plausible siblings) are untested.
