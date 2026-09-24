# Real example: example_order_form_redacted

The real (redacted) order form referenced in this project. Expected answer and catalog are
copied verbatim; The spec gives no parsing instructions for this catalog.

- `input.pdf` - **missing**: the PDF was not included with the materials we received. Drop it here
  as `input.pdf` to run this case.
- `catalog.json` - the 5-SKU catalog The spec specifies for this example (not the 21-SKU synthetic one).
- `expected.json` - the expected extraction (`sku_reference` corresponds to our `sku_code`).
  The spec gives only contract items, not order-form header fields.

What The spec says this case tests:
- Prices listed per year across 3 columns; each item's total is the sum across years.
- SKU-004 and SKU-005 are in the catalog but not in the form - they must not be extracted.
- Implementation services are mentioned but delivered by a third-party partner - not a contract item.
- The invoicing schedule section confirms yearly billing and should be consistent with the items.

Run: `python parse.py --catalog edge_cases/example_order_form_redacted/catalog.json edge_cases/example_order_form_redacted/input.pdf --out runs/example`
