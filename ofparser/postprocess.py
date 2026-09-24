"""Turn an accepted submission into the final output record."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .catalog import Catalog
from .schema import ContractItem, Submission
from .validator import Issue, parse_iso, price_ratio, term_months, RATIO_TOLERANCE

PERIOD_MONTHS_TO_FREQUENCY = {1: "monthly", 3: "quarterly", 6: "biannually", 12: "yearly"}


def infer_frequency(item: ContractItem) -> Tuple[Optional[str], Optional[dict]]:
    """Fallback when the document says nothing about billing: one invoice per pricing period.

    Returns (frequency, ambiguity) where ambiguity is {"candidates", "reason"} or None. A single price covering the whole term is one invoice,
    which is "one-time" - but if the term is itself exactly one standard period (e.g. 12 months),
    the matching periodic label ("yearly") is equally valid, so we return no answer and say why.
    """
    ratio = price_ratio(item)
    if ratio is None or item.period_amounts or not (item.service_start_date and item.service_end_date):
        return None, None
    n = ratio.to_integral_value()
    if n < 1 or abs(ratio - n) > RATIO_TOLERANCE:
        return None, None
    try:
        months = term_months(parse_iso(item.service_start_date), parse_iso(item.service_end_date))
    except ValueError:
        return None, None
    if n == 1:
        if months in PERIOD_MONTHS_TO_FREQUENCY:
            label = PERIOD_MONTHS_TO_FREQUENCY[months]
            return None, {"candidates": ["one-time", label],
                          "reason": f"One price covers the whole {months}-month term, so it is billed once; that fits "
                                    f"both 'one-time' and '{label}', and the document does not state the billing frequency."}
        return "one-time", None
    period = months / int(n)
    return (PERIOD_MONTHS_TO_FREQUENCY.get(period) if period == int(period) else None), None


def build_output(sub: Submission, catalog: Catalog, unresolved: List[Issue], notes: List[Issue] = ()) -> dict:
    ambiguous: Dict[Optional[int], Dict[str, dict]] = {}
    for a in sub.ambiguities:
        ambiguous.setdefault(a.item_index, {})[a.field] = {"candidates": a.candidates, "reason": a.reason}

    items = []
    for idx, item in enumerate(sub.contract_items):
        sku = catalog.by_code.get(item.sku_code, {})
        item_ambiguous = dict(ambiguous.get(idx, {}))
        frequency, frequency_source = item.invoicing_frequency, "stated" if item.invoicing_frequency else None
        if frequency is None and "invoicing_frequency" not in item_ambiguous:
            frequency, ambiguity = infer_frequency(item)
            if frequency:
                frequency_source = "inferred_from_pricing"
            elif ambiguity:
                frequency_source = "ambiguous"
                item_ambiguous["invoicing_frequency"] = ambiguity
        elif "invoicing_frequency" in item_ambiguous:
            frequency_source = "ambiguous"
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
            "invoicing_frequency_source": frequency_source,
            "payment_terms": item.payment_terms,
            "special_notes": item.special_notes,
            "ambiguous_fields": item_ambiguous,
            "source_row": item.source_row,
            "evidence": item.evidence,
        })
    order_form = sub.order_form.model_dump()
    order_form["ambiguous_fields"] = ambiguous.get(None, {})
    return {
        "order_form": order_form,
        "contract_items_count": len(items),
        "contract_items": items,
        "explicitly_excluded_skus": sub.explicitly_excluded_skus,
        "overrides": [o.model_dump() for o in sub.overrides],
        "needs_review": bool(unresolved),
        "unresolved_issues": [i.to_dict() for i in unresolved],
        "review_notes": [i.to_dict() for i in notes],
    }
