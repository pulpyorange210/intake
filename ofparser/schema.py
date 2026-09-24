"""Submission schema the agent fills via the submit_extraction tool."""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Frequency = Literal["monthly", "quarterly", "biannually", "yearly", "one-time"]
ScheduleType = Literal["upfront", "recurring", "milestone-based", "usage-based", "hybrid"]
PricePeriod = Literal["month", "quarter", "half_year", "year", "term"]


class Discount(BaseModel):
    type: Literal["percent", "amount"]
    value: float


class PeriodAmount(BaseModel):
    label: str = Field(description="Period label as written, e.g. 'Year 1'")
    amount: float


class ContractItem(BaseModel):
    sku_code: str = Field(description="Code of the matching catalog SKU")
    source_row: str = Field(description="Verbatim text of the priced line this item comes from")
    currency: Optional[str] = Field(description="ISO 4217 code, e.g. USD")
    total_listed_value: Optional[float] = Field(description="Total value of this line over its whole service period")
    quantity: Optional[float]
    unit_price: Optional[float]
    unit_price_period: Optional[PricePeriod] = Field(description="Period the unit price covers; null if unclear")
    period_amounts: Optional[List[PeriodAmount]] = Field(description="Per-period amounts if the document lists them separately")
    discount: Optional[Discount]
    service_start_date: Optional[str] = Field(description="YYYY-MM-DD")
    service_end_date: Optional[str] = Field(description="YYYY-MM-DD")
    invoicing_schedule_type: Optional[ScheduleType] = Field(description="Only from explicit billing statements; else null")
    invoicing_frequency: Optional[Frequency] = Field(description="Only from explicit billing statements; else null")
    payment_terms: Optional[str]
    special_notes: Optional[str]
    evidence: Dict[str, str] = Field(description="Field name -> short verbatim quote supporting it, for every non-null field")


class OrderFormHeader(BaseModel):
    customer_name: Optional[str]
    vendor_name: Optional[str]
    effective_date: Optional[str] = Field(description="YYYY-MM-DD, the date the document says it becomes effective")
    contract_signed_date_buying_company: Optional[str] = Field(description="YYYY-MM-DD")
    contract_signed_date_selling_company: Optional[str] = Field(description="YYYY-MM-DD")
    currency: Optional[str]
    grand_total: Optional[float] = Field(description="Grand total printed on the form, if any")
    grand_total_label: Optional[str] = Field(description="Label of the grand total line as written")
    evidence: Dict[str, str] = Field(description="Field name -> short verbatim quote supporting it")


class Override(BaseModel):
    check: str = Field(description="Name of the warning being overridden")
    item_index: Optional[int] = Field(description="Index of the contract item the warning refers to, or null for form-level")
    reason: str = Field(description="Why the submitted value is correct as written in the document")


class Ambiguity(BaseModel):
    item_index: Optional[int] = Field(description="Index of the contract item, or null for an order_form field")
    field: str = Field(description="Name of the field left null because it is ambiguous")
    candidates: List[str] = Field(description="The readings the document supports")
    reason: str = Field(description="Why the document does not decide between them")


class Submission(BaseModel):
    order_form: OrderFormHeader
    contract_items: List[ContractItem]
    explicitly_excluded_skus: List[str] = Field(
        description="Catalog SKU codes the document explicitly says are NOT part of this order")
    ambiguities: List[Ambiguity] = Field(default_factory=list)
    overrides: List[Override] = Field(default_factory=list)


def _inline_refs(schema: dict) -> dict:
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def submission_json_schema() -> dict:
    return _inline_refs(Submission.model_json_schema())
