"""Deterministic checks on a submission.

Hard errors always go back to the agent (unknown SKU, amount with no source, bad dates).
Warnings flag things that are often mistakes; the agent may override them with a written
reason, so it is never pushed into altering a correct value just to pass a check.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from .catalog import Catalog
from .pdf import add_months, cents, normalize_for_match, to_decimal
from .schema import ContractItem, InferredDate, OrderFormHeader, Submission

# Item fields every contract item is expected to have; a null needs an ambiguity entry or an override.
EXPECTED_ITEM_FIELDS = ("currency", "total_listed_value", "quantity", "service_start_date", "service_end_date")
HEADER_DATE_FIELDS = ("effective_date", "contract_signed_date_buying_company", "contract_signed_date_selling_company")
ITEM_DATE_FIELDS = ("service_start_date", "service_end_date")

# Billing/pricing period lengths in months that are considered sensible.
SENSIBLE_PERIOD_MONTHS = {1, 3, 6, 12}
RATIO_TOLERANCE = Decimal("0.001")


@dataclass
class Issue:
    severity: str  # "error" | "warning" | "note" (recorded for review, never sent back to the agent)
    check: str
    item_index: Optional[int]
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationContext:
    catalog: Catalog
    doc_text: str
    doc_numbers: Set[Decimal]
    computed_numbers: Set[Decimal]
    has_text_layer: bool = True  # False for scanned PDFs: grounding and quote checks can't apply
    doc_dates: Set[dt.date] = field(default_factory=set)

    @property
    def normalized_text(self) -> str:
        return normalize_for_match(self.doc_text)


def parse_iso(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def term_months(start: dt.date, end: dt.date) -> int:
    """Whole months covered by an inclusive start..end term (364/365-day terms -> 12)."""
    end_exclusive = end + dt.timedelta(days=1)
    months = (end_exclusive.year - start.year) * 12 + (end_exclusive.month - start.month)
    months += (end_exclusive.day - start.day) / 30.0
    return int(round(months))


def apply_inferred(entry: InferredDate) -> dt.date:
    return add_months(parse_iso(entry.from_date), entry.add_months) + dt.timedelta(days=entry.add_days)


def quote_found(quote: str, normalized_text: str) -> bool:
    """A quote may join non-adjacent fragments with '...' (e.g. a party name and the date in its
    signature block, or a table row split across lines); each fragment must appear, in order."""
    pos = 0
    for fragment in re.split(r"\.\.\.|…", quote):
        fragment = normalize_for_match(fragment)
        if not fragment:
            continue
        pos = normalized_text.find(fragment, pos)
        if pos < 0:
            return False
        pos += len(fragment)
    return True


def price_ratio(item: ContractItem) -> Optional[Decimal]:
    """total / (quantity * unit_price), after undoing any stated discount."""
    if not item.total_listed_value or not item.quantity or not item.unit_price:
        return None
    gross = to_decimal(item.total_listed_value)
    if item.discount:
        if item.discount.type == "percent" and item.discount.value < 100:
            gross = gross / (1 - to_decimal(item.discount.value) / 100)
        elif item.discount.type == "amount":
            gross = gross + to_decimal(item.discount.value)
    return gross / (to_decimal(item.quantity) * to_decimal(item.unit_price))


def validate(sub: Submission, ctx: ValidationContext) -> List[Issue]:
    issues: List[Issue] = []
    err = lambda check, idx, msg: issues.append(Issue("error", check, idx, msg))
    warn = lambda check, idx, msg: issues.append(Issue("warning", check, idx, msg))
    grounded = ctx.doc_numbers | ctx.computed_numbers
    normalized_text = ctx.normalized_text

    def check_amount(value, label, idx):
        if value is not None and ctx.has_text_layer and cents(value) not in grounded:
            err("ungrounded_amount", idx,
                f"{label}={value} does not appear in the document and was not produced by the compute tool "
                f"from document values. Copy it exactly from the document or derive it with compute.")

    inferred: Dict[Tuple[Optional[int], str], InferredDate] = {(d.item_index, d.field): d for d in sub.inferred_dates}

    def check_date(value, label, idx) -> Optional[dt.date]:
        if value is None:
            return None
        try:
            date = parse_iso(value)
        except ValueError:
            err("bad_date", idx, f"{label}={value!r} is not a valid YYYY-MM-DD date.")
            return None
        if ctx.has_text_layer and date not in ctx.doc_dates:
            problem = inferred_date_problem(inferred.get((idx, label)), date)
            if problem:
                warn("date_not_in_document", idx,
                     f"{label}={value} does not appear in the document in any date format. {problem} "
                     f"If it is printed, check for a misread. If it is calculated from a printed date "
                     f"(e.g. end = start + term), add an inferred_dates entry with from_date, add_months, "
                     f"add_days and an explanation. Otherwise leave it null.")
        return date

    def inferred_date_problem(entry: Optional[InferredDate], date: dt.date) -> Optional[str]:
        if entry is None:
            return "There is no inferred_dates entry for it."
        try:
            base = parse_iso(entry.from_date)
        except ValueError:
            return f"Its inferred_dates from_date {entry.from_date!r} is not a valid YYYY-MM-DD date."
        if base not in ctx.doc_dates:
            return f"Its inferred_dates from_date {entry.from_date} is not printed in the document either."
        result = apply_inferred(entry)
        if result != date:
            return (f"Its inferred_dates calculation gives {result} ({entry.from_date} + {entry.add_months} "
                    f"months + {entry.add_days} days), not {date}.")
        return None

    def check_quotes(evidence: dict, idx, extra: Optional[str] = None):
        if not ctx.has_text_layer:
            return
        quotes = dict(evidence)
        if extra is not None:
            quotes["source_row"] = extra
        missing = [k for k, q in quotes.items() if q and not quote_found(q, normalized_text)]
        if missing:
            # Non-blocking: layout extraction often splits wrapped rows and side-by-side blocks, so a
            # faithful quote can fail to match. Amounts and SKUs are checked independently above.
            issues.append(Issue("note", "evidence_not_found", idx,
                                f"quotes for {missing} were not found verbatim in the text layer"))

    if not ctx.has_text_layer:
        issues.append(Issue("note", "no_text_layer", None,
                            "the PDF has no text layer (likely scanned); amounts and quotes could not be "
                            "checked against the document text"))

    flagged = {(a.item_index, a.field) for a in sub.ambiguities}

    # ---- header ----
    h = sub.order_form
    for label in HEADER_DATE_FIELDS:
        check_date(getattr(h, label), label, None)
        if getattr(h, label) is None and (None, label) not in flagged:
            warn("missing_value", None,
                 f"order_form.{label} is null. If the document states it, extract it; if it is genuinely "
                 f"ambiguous, add an ambiguity entry; if the document does not state it, override this "
                 f"warning with that reason. A null here is flagged for review either way.")
    check_amount(h.grand_total, "order_form.grand_total", None)
    check_quotes(h.evidence, None)

    # ---- items ----
    for i, item in enumerate(sub.contract_items):
        if item.sku_code not in ctx.catalog.by_code:
            err("sku_not_in_catalog", i, f"sku_code {item.sku_code!r} is not in the catalog.")
        if item.currency is not None and not re.fullmatch(r"[A-Z]{3}", item.currency):
            err("bad_currency", i, f"currency {item.currency!r} must be an ISO 4217 code like USD.")
        check_amount(item.total_listed_value, "total_listed_value", i)
        check_amount(item.unit_price, "unit_price", i)
        for p in item.period_amounts or []:
            check_amount(p.amount, f"period_amounts[{p.label}]", i)
        if item.discount and item.discount.type == "amount":
            check_amount(item.discount.value, "discount", i)
        start = check_date(item.service_start_date, "service_start_date", i)
        end = check_date(item.service_end_date, "service_end_date", i)
        if start and end and start > end:
            err("date_order", i, f"service_start_date {start} is after service_end_date {end}.")
        check_quotes(item.evidence, i, item.source_row)
        for field in EXPECTED_ITEM_FIELDS:
            if getattr(item, field) is None and (i, field) not in flagged:
                warn("missing_value", i,
                     f"{field} is null. If the document states it, extract it (quantity defaults to 1 when "
                     f"not stated); if it is genuinely ambiguous, add an ambiguity entry; if a SKU parsing "
                     f"instruction requires null, override this warning with that reason. A null here is "
                     f"flagged for review either way.")

        if item.sku_code in sub.explicitly_excluded_skus:
            warn("excluded_conflict", i,
                 f"{item.sku_code} is listed in explicitly_excluded_skus. Re-read this priced line: is it really "
                 f"this SKU, or a more/less specific catalog SKU with a similar name?")

        if item.period_amounts:
            total = sum(to_decimal(p.amount) for p in item.period_amounts)
            if item.total_listed_value is not None and cents(total) != cents(item.total_listed_value):
                warn("period_amounts_sum", i,
                     f"period_amounts sum to {cents(total)} but total_listed_value is {item.total_listed_value}.")
            continue  # escalating prices: the ratio checks below do not apply

        ratio = price_ratio(item)
        if ratio is None:
            continue
        n = ratio.to_integral_value()
        if n < 1 or abs(ratio - n) > RATIO_TOLERANCE:
            warn("price_ratio_not_integer", i,
                 f"total / (quantity x unit_price) = {ratio:.4f}, not a whole number of periods. "
                 f"Check for a misread digit, wrong column, or wrong quantity.")
        elif n > 1 and start and end:
            months = term_months(start, end)
            period = Decimal(months) / n
            if period not in SENSIBLE_PERIOD_MONTHS:
                warn("period_mismatch", i,
                     f"price covers {n} periods over a {months}-month term ({period:.2f} months each), "
                     f"which is not monthly/quarterly/semiannual/yearly. Check the dates, quantity, and prices.")

    # ---- ambiguity entries must point at a real, null field ----
    item_fields, header_fields = set(ContractItem.model_fields), set(OrderFormHeader.model_fields)
    for a in sub.ambiguities:
        if a.item_index is None:
            target, fields, where = sub.order_form, header_fields, "order_form"
        elif 0 <= a.item_index < len(sub.contract_items):
            target, fields, where = sub.contract_items[a.item_index], item_fields, f"item {a.item_index}"
        else:
            err("bad_ambiguity", a.item_index, f"ambiguity item_index {a.item_index} does not exist.")
            continue
        if a.likely is not None and a.likely not in a.candidates:
            err("bad_ambiguity", a.item_index, f"ambiguity 'likely' value {a.likely!r} is not one of its candidates.")
        if a.field not in fields:
            err("bad_ambiguity", a.item_index,
                f"ambiguity field {a.field!r} is not a field of {where}. Item fields need the item's index.")
        elif getattr(target, a.field) is not None:
            err("bad_ambiguity", a.item_index,
                f"{where}.{a.field} is flagged ambiguous but has a value; leave it null or drop the ambiguity.")

    # ---- inferred date entries must point at a date field ----
    for d in sub.inferred_dates:
        allowed = HEADER_DATE_FIELDS if d.item_index is None else ITEM_DATE_FIELDS
        if d.item_index is not None and not 0 <= d.item_index < len(sub.contract_items):
            err("bad_inferred_date", d.item_index, f"inferred_dates item_index {d.item_index} does not exist.")
        elif d.field not in allowed:
            err("bad_inferred_date", d.item_index,
                f"inferred_dates field {d.field!r} is not a date field of "
                f"{'order_form' if d.item_index is None else f'item {d.item_index}'} (allowed: {', '.join(allowed)}).")

    # ---- form-level totals ----
    if h.grand_total is not None and sub.contract_items:
        totals = [it.total_listed_value for it in sub.contract_items if it.total_listed_value is not None]
        if totals and cents(sum(to_decimal(t) for t in totals)) != cents(h.grand_total):
            warn("grand_total_mismatch", None,
                 f"item totals sum to {cents(sum(to_decimal(t) for t in totals))} but the form's "
                 f"{h.grand_total_label or 'grand total'} is {h.grand_total}. Check for a missed or extra item, "
                 f"or a total that covers a different scope.")
    return issues


def active_issues(issues: List[Issue], sub: Submission) -> List[Issue]:
    """Drop warnings the agent has overridden with a reason."""
    overridden = {(o.check, o.item_index) for o in sub.overrides if o.reason.strip()}
    return [i for i in issues if i.severity == "error"
            or (i.severity == "warning" and (i.check, i.item_index) not in overridden)]
