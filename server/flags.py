"""Map the parser's output onto review rows and severity-graded flags.

The parser and checker already record every doubt; this module only grades them for the review queue:

- high: the value can't be used as is. A blank important field (missing_fields: not found, or left blank
  because the document reads two ways), an ambiguous SKU, or a checker issue left unresolved after the
  agent's last submission. Approval is blocked until a reviewer accepts or edits it.
- medium: a value was given, but with a recorded doubt. Billing frequency flagged ambiguous with its
  alternative, another field left blank as ambiguous, or a date kept although it isn't printed in the document.
- low: worth a glance. A date calculated from a printed one (with the calculation), or a scanned PDF whose
  amounts couldn't be checked against a text layer.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from ofparser.pdf import normalize_for_match
from ofparser.postprocess import sku_value
from ofparser.validator import quote_found

SEVERITY_RANK = {None: 0, "low": 1, "medium": 2, "high": 3}

# Review-row column -> field name in the parser's output.
ITEM_COLUMNS = {
    "sku": "sku_code", "description": "sku_code", "qty": "quantity", "unit_price": "unit_price",
    "amount": "total_listed_value", "service_start": "service_start_date", "service_end": "service_end_date",
    "billing_terms": "invoicing_frequency", "currency": "currency", "payment_terms": "payment_terms",
}
COLUMN_OF = {"sku_code": "sku", "quantity": "qty", "unit_price": "unit_price", "total_listed_value": "amount",
             "service_start_date": "service_start", "service_end_date": "service_end",
             "invoicing_frequency": "billing_terms", "currency": "currency", "payment_terms": "payment_terms"}
HEADER_FIELDS = ("customer_name", "vendor_name", "effective_date", "contract_signed_date_buying_company",
                 "contract_signed_date_selling_company", "currency", "grand_total")
LABELS = {"sku": "SKU", "qty": "Quantity", "unit_price": "Unit price", "amount": "Amount",
          "service_start": "Service start", "service_end": "Service end", "billing_terms": "Billing frequency",
          "currency": "Currency", "payment_terms": "Payment terms", "effective_date": "Effective date",
          "contract_signed_date_buying_company": "Customer signature date",
          "contract_signed_date_selling_company": "Vendor signature date", "grand_total": "Grand total",
          "customer_name": "Customer", "vendor_name": "Vendor"}


def label(field: Optional[str]) -> str:
    return LABELS.get(COLUMN_OF.get(field, field), field or "Form")


def _flag(line_index, field, severity, check, reason) -> dict:
    return {"line_index": line_index, "field": COLUMN_OF.get(field, field), "severity": severity, "check": check,
            "reason": reason}


def _field_flags(target: dict, line_index: Optional[int]) -> List[dict]:
    """Flags carried on an item or the order-form header: blanks, ambiguities, calculated dates."""
    flags = []
    missing = target.get("missing_fields") or {}
    for name, m in missing.items():
        flags.append(_flag(line_index, name, "high", "missing_value", f"{label(name)} is blank: {m['reason']}"))
    for name, a in (target.get("ambiguous_fields") or {}).items():
        if name in missing:
            continue
        likely = f" Likely {a['likely']}." if a.get("likely") else ""
        flags.append(_flag(line_index, name, "medium", "ambiguous",
                           f"{label(name)} reads more than one way ({', '.join(a['candidates'])}): {a['reason']}{likely}"))
    for name, d in (target.get("inferred_dates") or {}).items():
        flags.append(_flag(line_index, name, "low", "inferred_date",
                           f"{label(name)} is calculated, not printed: {d['explanation']}"))
    return flags


def derive_flags(output: dict) -> List[dict]:
    flags = []
    for i, item in enumerate(output.get("contract_items") or []):
        sku = item.get("sku_code")
        if isinstance(sku, dict) and sku.get("ambiguous"):
            flags.append(_flag(i, "sku_code", "high", "sku_ambiguous",
                               f"SKU could be {' or '.join([sku['value']] + sku['alternatives'])}: {sku.get('reason')}"))
        freq = item.get("invoicing_frequency")
        if isinstance(freq, dict) and freq.get("ambiguous"):
            alts = " / ".join(freq.get("alternatives") or [])
            reason = (f"Billed '{freq['value']}', but '{alts}' fits too: {freq.get('reason')}" if freq.get("value")
                      else f"Billing frequency unclear ({alts}): {freq.get('reason')}")
            flags.append(_flag(i, "invoicing_frequency", "medium", "frequency_ambiguous", reason))
        flags += _field_flags(item, i)
    flags += _field_flags(output.get("order_form") or {}, None)
    for issue in output.get("unresolved_issues") or []:
        flags.append(_flag(issue["item_index"], None, "high", issue["check"],
                           f"Checker issue not resolved by the model: {issue['message']}"))
    for note in output.get("review_notes") or []:
        if note["check"] == "date_not_in_document":
            flags.append(_flag(note["item_index"], None, "medium", note["check"], note["message"]))
        elif note["check"] == "no_text_layer":
            flags.append(_flag(note["item_index"], None, "low", note["check"], note["message"]))
        # evidence_not_found (a quote that doesn't match the text layer verbatim) is not a flag: it fires on most
        # forms because of layout quirks and says nothing about the value, which the checker grounds separately.
        # The viewer shows it anyway, when a field's quote can't be highlighted.
    return flags


# ---- source locations for click-to-highlight ----

def split_pages(text: str) -> List[str]:
    pages = text.split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def page_of(quote: Optional[str], pages_norm: List[str]) -> Optional[int]:
    """1-based page holding the whole quote (all its '...' fragments, in order); failing that, the page of its
    first fragment, so a quote split across a page break still lands near its start."""
    if not quote:
        return None
    for i, page in enumerate(pages_norm, start=1):
        if quote_found(quote, page):
            return i
    for fragment in re.split(r"\.\.\.|…", quote):
        frag = normalize_for_match(fragment)
        if frag:
            return next((i for i, page in enumerate(pages_norm, start=1) if frag in page), None)
    return None


def located(evidence: Dict[str, str], pages_norm: List[str]) -> Dict[str, dict]:
    return {field: {"quote": quote, "page": page_of(quote, pages_norm)} for field, quote in (evidence or {}).items()}


def item_row(item: dict, index: int, pages_norm: List[str]) -> dict:
    evidence = located(item.get("evidence") or {}, pages_norm)
    by_column = {}
    for column, field in ITEM_COLUMNS.items():
        source = evidence.get(field) or evidence.get("source_row")
        if source:
            by_column[column] = source
    freq = item.get("invoicing_frequency")
    source_row = item.get("source_row")
    return {
        "line_index": index,
        "sku": sku_value(item.get("sku_code")),
        "description": item.get("name"),
        "qty": item.get("quantity"),
        "unit_price": item.get("unit_price"),
        "amount": item.get("total_listed_value"),
        "service_start": item.get("service_start_date"),
        "service_end": item.get("service_end_date"),
        "billing_terms": freq.get("value") if isinstance(freq, dict) else freq,
        "currency": item.get("currency"),
        "payment_terms": item.get("payment_terms"),
        "source_page": page_of(source_row, pages_norm),
        "source_text": source_row,
        "evidence": by_column,
    }


def header_record(order_form: dict, pages_norm: List[str]) -> dict:
    evidence = located(order_form.get("evidence") or {}, pages_norm)
    return {"values": {f: order_form.get(f) for f in HEADER_FIELDS},
            "evidence": {f: evidence[f] for f in HEADER_FIELDS if f in evidence}}


def max_severity(severities) -> Optional[str]:
    best = None
    for s in severities:
        if SEVERITY_RANK[s] > SEVERITY_RANK[best]:
            best = s
    return best
