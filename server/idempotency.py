"""Idempotency keys for sheet rows: the same approved line always hashes to the same key."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

# Numbers are written as fixed-point strings with this many decimals, so 1, 1.0 and "1.000" are one value.
DECIMALS = Decimal("0.000001")


def _canonical(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            return format(Decimal(str(value)).quantize(DECIMALS), "f")
        except InvalidOperation:
            return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return str(value)


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace, numbers as fixed decimal strings, strings trimmed."""
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def line_key(form_content_hash: str, line_index: int, final_values: dict) -> str:
    """sha256 over {form_content_hash, line_index, final_field_values}. Re-approving the same form with the
    same values gives the same key; a deliberately edited value gives a new one."""
    payload = {"form_content_hash": form_content_hash, "line_index": line_index, "final_field_values": final_values}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
