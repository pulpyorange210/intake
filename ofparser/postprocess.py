"""Turn an accepted submission into the final output record."""
from __future__ import annotations

from typing import Dict, List, Optional

from .catalog import Catalog
from .schema import ContractItem, Submission
from .validator import (EXPECTED_ITEM_FIELDS, HEADER_DATE_FIELDS, Issue, parse_iso, price_ratio, term_months,
                        RATIO_TOLERANCE)

PERIOD_MONTHS_TO_FREQUENCY = {1: "monthly", 3: "quarterly", 6: "biannually", 12: "yearly"}


def frequency_block(value=None, source=None, alternatives=(), reason=None) -> dict:
    """invoicing_frequency is always this block, so the ambiguity flag sits next to the value."""
    return {"value": value, "source": source, "ambiguous": bool(alternatives) or (value is None and bool(reason)),
            "alternatives": list(alternatives), "reason": reason}


def infer_frequency(item: ContractItem) -> dict:
    """Fallback when the document says nothing about billing: one invoice per pricing period.

    A single price covering the whole term is one invoice for the full amount, labelled "one-time".
    If the term is itself exactly one standard period (e.g. 12 months), the periodic label ("yearly")
    describes the same single invoice equally well, so the value is flagged ambiguous with that
    alternative next to it.
    """
    none = frequency_block()
    ratio = price_ratio(item)
    if ratio is None or item.period_amounts or not (item.service_start_date and item.service_end_date):
        return none
    n = ratio.to_integral_value()
    if n < 1 or abs(ratio - n) > RATIO_TOLERANCE:
        return none
    try:
        months = term_months(parse_iso(item.service_start_date), parse_iso(item.service_end_date))
    except ValueError:
        return none
    if n == 1:
        if months in PERIOD_MONTHS_TO_FREQUENCY:
            label = PERIOD_MONTHS_TO_FREQUENCY[months]
            return frequency_block(
                "one-time", "inferred_from_pricing", [label],
                f"One invoice for the full amount over the {months}-month term (a single price covers the whole "
                f"term; the document does not state billing). 'one-time' and '{label}' both describe this; the "
                f"document doesn't distinguish them.")
        return frequency_block("one-time", "inferred_from_pricing")
    period = months / int(n)
    label = PERIOD_MONTHS_TO_FREQUENCY.get(period) if period == int(period) else None
    return frequency_block(label, "inferred_from_pricing") if label else none


def missing_fields(target, fields, ambiguous: Dict[str, dict], override_reason: Optional[str]) -> Dict[str, dict]:
    """A note on every blank important field saying why it is blank, so a null never passes silently."""
    missing = {}
    for name in fields:
        if getattr(target, name) is not None:
            continue
        if name in ambiguous:
            missing[name] = {"status": "ambiguous", "reason": f"more than one reading (see ambiguous_fields): "
                                                              f"{ambiguous[name]['reason']}"}
        elif override_reason:
            missing[name] = {"status": "not_found", "reason": f"the model's reason: {override_reason}"}
        else:
            missing[name] = {"status": "not_found", "reason": "not found in the document; no reason given"}
    return missing


def build_output(sub: Submission, catalog: Catalog, unresolved: List[Issue], notes: List[Issue] = ()) -> dict:
    ambiguous: Dict[Optional[int], Dict[str, dict]] = {}
    for a in sub.ambiguities:
        ambiguous.setdefault(a.item_index, {})[a.field] = {
            "candidates": a.candidates, "likely": a.likely, "likely_reason": a.likely_reason, "reason": a.reason}
    inferred: Dict[Optional[int], Dict[str, dict]] = {}
    for d in sub.inferred_dates:
        inferred.setdefault(d.item_index, {})[d.field] = d.model_dump(exclude={"item_index", "field"})
    override_reasons = {(o.check, o.item_index): o.reason for o in sub.overrides}
    notes = list(notes)
    for o in sub.overrides:
        if o.check == "date_not_in_document":
            notes.append(Issue("note", "date_not_in_document", o.item_index,
                               f"a date not printed in the document was kept with the model's reason: {o.reason}"))

    items = []
    for idx, item in enumerate(sub.contract_items):
        sku = catalog.by_code.get(item.sku_code, {})
        item_ambiguous = dict(ambiguous.get(idx, {}))
        model_flag = item_ambiguous.pop("invoicing_frequency", None)
        if item.invoicing_frequency:
            frequency = frequency_block(item.invoicing_frequency, "stated")
        elif model_flag:
            frequency = frequency_block(None, "document_ambiguous", model_flag["candidates"], model_flag["reason"])
        else:
            frequency = infer_frequency(item)
        item_missing = missing_fields(item, EXPECTED_ITEM_FIELDS, item_ambiguous,
                                      override_reasons.get(("missing_value", idx)))
        notes += [Issue("note", "missing_value", idx, f"{name} is blank: {m['reason']}")
                  for name, m in item_missing.items()]
        items.append({
            "name": sku.get("name"),
            "sku_id": sku.get("id"),
            "sku_code": item.sku_code,
            "currency": item.currency,
            "total_listed_value": item.total_listed_value,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "unit_price_period": item.unit_price_period,
            "period_amounts": [p.model_dump() for p in item.period_amounts] if item.period_amounts else None,
            "discount": item.discount.model_dump() if item.discount else None,
            "service_start_date": item.service_start_date,
            "service_end_date": item.service_end_date,
            "invoicing_schedule_type": item.invoicing_schedule_type,
            "invoicing_frequency": frequency,
            "payment_terms": item.payment_terms,
            "special_notes": item.special_notes,
            "ambiguous_fields": item_ambiguous,
            "missing_fields": item_missing,
            "inferred_dates": inferred.get(idx, {}),
            "source_row": item.source_row,
            "evidence": item.evidence,
        })
    order_form = sub.order_form.model_dump()
    order_form["ambiguous_fields"] = ambiguous.get(None, {})
    order_form["missing_fields"] = missing_fields(sub.order_form, HEADER_DATE_FIELDS, order_form["ambiguous_fields"],
                                                  override_reasons.get(("missing_value", None)))
    order_form["inferred_dates"] = inferred.get(None, {})
    notes += [Issue("note", "missing_value", None, f"order_form.{name} is blank: {m['reason']}")
              for name, m in order_form["missing_fields"].items()]
    flagged_for_review = [n for n in notes if n.check in ("missing_value", "date_not_in_document")]
    return {
        "order_form": order_form,
        "contract_items_count": len(items),
        "contract_items": items,
        "explicitly_excluded_skus": sub.explicitly_excluded_skus,
        "overrides": [o.model_dump() for o in sub.overrides],
        "needs_review": bool(unresolved or flagged_for_review),
        "unresolved_issues": [i.to_dict() for i in unresolved],
        "review_notes": [i.to_dict() for i in notes],
    }
