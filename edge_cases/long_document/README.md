# Long documents: the real example form buried in a long contract

Tests page selection for long PDFs. Each variant is seeded contract boilerplate with the 5 original pages of
`../example_order_form_redacted/input.pdf` inserted unchanged, plus decoy pages that look relevant but aren't:
a table of contents pointing to the order form, an optional-services rate card (priced, using catalog product
names, explicitly not purchased), SLA tables full of numbers and percentages, amendment logs dense with dates
and section numbers, and occasional dollar amounts inside ordinary clauses.

- `variants.json` - each variant's length, where the form is, which expected file applies, and the pages that
  hold information the order needs (used for page recall).
- `n1000_scattered` - the form spread apart: its first page split into three redrawn pages (service term p.120,
  pricing p.415, invoicing schedule p.640), its signature page at p.880, and a generated amendment at p.955
  that changes Premium Support to $45,000.00 a year. Its expected output is `expected_scattered.json`.
  The split pages are redrawn word by word from the original page (cropping a copy isn't enough: the model
  still reads text outside the crop), so headings show small spacing artifacts; every amount and date is intact.
- `generated/` - the PDFs (gitignored; rebuild them, the output is byte-for-byte reproducible):
  `.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python scripts/make_long_doc.py`

Expected output is the example's own `expected.json` (or `expected_scattered.json`), with its 5-SKU `catalog.json`.

```bash
.venv/bin/python parse.py --catalog edge_cases/example_order_form_redacted/catalog.json \
    edge_cases/long_document/generated/*.pdf --out runs/long_doc --workers 5
.venv/bin/python scripts/long_doc_report.py runs/long_doc     # add --long-doc select to parse.py for v0.9 mode
.venv/bin/python scripts/count_full_doc.py edge_cases/long_document/generated/*.pdf   # full-document baseline
```
