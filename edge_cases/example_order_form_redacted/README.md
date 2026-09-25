# Real example: example_order_form_redacted

The real (redacted) order form referenced in this project. Expected answer and catalog are
copied verbatim; The spec gives no parsing instructions for this catalog.

- `input.pdf` - the form itself, received after The spec (it was referenced as an attachment but
  wasn't in the materials at first).
- `catalog.json` - the 5-SKU catalog The spec specifies for this example (not the 21-SKU synthetic one).
- `expected.json` - the expected extraction (`sku_reference` corresponds to our `sku_code`).
  The spec gives only contract items, not order-form header fields.

What The spec says this case tests:
- Prices listed per year across 3 columns; each item's total is the sum across years.
- SKU-004 and SKU-005 are in the catalog but not in the form - they must not be extracted.
- Implementation services are mentioned but delivered by a third-party partner - not a contract item.
- The invoicing schedule section confirms yearly billing and should be consistent with the items.

Run: `python parse.py --catalog edge_cases/example_order_form_redacted/catalog.json edge_cases/example_order_form_redacted/input.pdf --out runs/example`

Result (`runs/example`, v0.8 code, $0.32): all 3 items found, none extra (SKU-004 listed as explicitly
excluded). Totals, unit prices, quantities, dates, schedule type and frequency match the expected
answer. Differences: payment terms quoted in full ("Net 55 from the date of the invoice"), and the
form-level employee-size note is on all 3 items instead of only SKU-001. No effective date is printed,
so the form is marked `needs_review` with the reason on that field. See the main README.
