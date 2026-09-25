"""Build submissions and prediction files from ground truth, so tests need no API calls."""
from __future__ import annotations

import json
from pathlib import Path

from ofparser.catalog import Catalog
from ofparser.pdf import dates_in, extract_text, has_text_layer, numbers_in
from ofparser.schema import Submission
from ofparser.validator import ValidationContext

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "synthetic_order_form_dataset_50"
CATALOG = Catalog.load(DATASET / "sku_catalog.json")
HEADER_FIELDS = ["effective_date", "contract_signed_date_buying_company", "contract_signed_date_selling_company"]


def gold(form: str) -> dict:
    return json.loads((DATASET / "ground_truth" / f"{form}.json").read_text())


def submission_from_gold(form: str) -> Submission:
    g = gold(form)
    items = [{
        "sku_code": i["sku_code"], "source_row": i["sku_name"], "currency": i["currency"],
        "total_listed_value": i["total_listed_value"], "quantity": i["quantity"], "unit_price": i["unit_price"],
        "unit_price_period": None, "period_amounts": None, "discount": None,
        "service_start_date": i["service_start_date"], "service_end_date": i["service_end_date"],
        "invoicing_schedule_type": None, "invoicing_frequency": None, "payment_terms": i["payment_terms"],
        "special_notes": None, "evidence": {},
    } for i in g["contract_items"]]
    header = {"customer_name": None, "vendor_name": None, "currency": "USD", "grand_total": None,
              "grand_total_label": None, "evidence": {}, **{f: g[f] for f in HEADER_FIELDS}}
    return Submission.model_validate({"order_form": header, "contract_items": items,
                                      "explicitly_excluded_skus": []})


def context(form: str, text_layer: bool = True) -> ValidationContext:
    text = extract_text(DATASET / "pdfs" / f"{form}.pdf") if text_layer else ""
    return ValidationContext(CATALOG, text, numbers_in(text), set(), has_text_layer(text), dates_in(text))


def prediction_from_gold(form: str) -> dict:
    """A parser output file whose values equal the ground truth."""
    g = gold(form)
    items = []
    for i in g["contract_items"]:
        item = {k: v for k, v in i.items() if k not in ("sku_id", "sku_name", "invoicing_frequency")}
        item["invoicing_frequency"] = {"value": i["invoicing_frequency"], "source": "stated", "ambiguous": False,
                                       "alternatives": [], "reason": None}
        item["ambiguous_fields"] = {}
        items.append(item)
    return {"order_form": {**{f: g[f] for f in HEADER_FIELDS}, "ambiguous_fields": {}},
            "contract_items_count": len(items), "contract_items": items, "needs_review": False}
