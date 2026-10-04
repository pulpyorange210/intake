# Big catalog: 2,000 SKUs with look-alikes

Tests how SKU matching scales when the catalog is far bigger than the 21-SKU synthetic one. The catalog is the
real 21 SKUs plus look-alikes and a plausible vendor's wider price book, seeded and byte-for-byte reproducible:

```bash
.venv/bin/python scripts/make_big_catalog.py        # -> generated/catalog_2000.json (gitignored)
```

Look-alikes differ from a real SKU by something an order form would print if it were sold: an edition
("Talent Management Enterprise Plus"), add-on vs base product, a region ("- EMEA") or deployment ("(EU Data
Residency)"), a unit ("- Per User"), a billing term, or a near-name sibling ("Premium Success Support"). None can
be confused with a real SKU through the forms' own abbreviations: "Premier Support" was dropped because forms
print "Prem. Support", which can't tell it from "Premium Support". Checked against every printed row of the 50
forms. The expected output is unchanged: the synthetic ground truth.

Runs (catalogs over 200 SKUs are searched with `search_catalog` unless `--catalog-mode inline`):

```bash
CAT=edge_cases/big_catalog/generated/catalog_2000.json
.venv/bin/python parse.py --catalog $CAT synthetic_order_form_dataset_50/pdfs/*.pdf --out runs/retrieval
.venv/bin/python parse.py --catalog $CAT <forms> --out runs/inline --catalog-mode inline --workers 1
.venv/bin/python scripts/catalog_report.py runs/inline runs/retrieval
```

Run inline mode with `--workers 1`: the 230K-token catalog is cached after the first form, and forms started in
parallel would each pay to write it.
