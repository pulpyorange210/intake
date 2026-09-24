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
