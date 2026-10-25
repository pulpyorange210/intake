"""Forms and their review state: storing an extraction, reviewer edits, the approval gate, and queue queries."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ofparser.catalog import Catalog
from ofparser.pdf import extract_text, normalize_for_match
from ofparser.validator import RATIO_TOLERANCE

from . import flags as F
from .db import Database, has_event, log_event, now

EDITABLE = ("sku", "qty", "unit_price", "amount", "service_start", "service_end", "billing_terms")
NUMBER_FIELDS = ("qty", "unit_price", "amount")
DATE_FIELDS = ("service_start", "service_end")
FREQUENCIES = ("monthly", "quarterly", "biannually", "yearly", "one-time")
HEADER_EDITABLE = ("effective_date", "contract_signed_date_buying_company", "contract_signed_date_selling_company",
                   "grand_total")


class ReviewError(Exception):
    """A request the review rules don't allow (bad value, approving with open high flags, ...)."""

    def __init__(self, message: str, fields: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.fields = fields or {}


# ---- storing an extraction ----

def store_extraction(db: Database, form_id: int, output: dict, pdf_path: Path) -> List[dict]:
    """Replace the form's review rows with a fresh extraction. Returns the flags."""
    try:
        text = extract_text(pdf_path)
    except Exception:  # noqa: BLE001 - locating quotes is a convenience; the extraction itself already ran
        text = ""
    pages_norm = [normalize_for_match(p) for p in F.split_pages(text)]
    flags = F.derive_flags(output)
    by_item: Dict[Optional[int], List[dict]] = {}
    for flag in flags:
        by_item.setdefault(flag["line_index"], []).append(flag)
    header = F.header_record(output.get("order_form") or {}, pages_norm)
    with db.transaction() as conn:
        conn.execute("DELETE FROM flags WHERE form_id = ?", (form_id,))
        conn.execute("DELETE FROM line_items WHERE form_id = ?", (form_id,))
        for i, item in enumerate(output.get("contract_items") or []):
            row = F.item_row(item, i, pages_norm)
            item_flags = by_item.get(i, [])
            conn.execute(
                """INSERT INTO line_items (form_id, line_index, sku, description, qty, unit_price, amount,
                   service_start, service_end, billing_terms, currency, payment_terms, flag_severity, flag_reason,
                   source_page, source_text, evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (form_id, i, row["sku"], row["description"], row["qty"], row["unit_price"], row["amount"],
                 row["service_start"], row["service_end"], row["billing_terms"], row["currency"],
                 row["payment_terms"], F.max_severity(f["severity"] for f in item_flags),
                 "\n".join(f["reason"] for f in item_flags) or None, row["source_page"], row["source_text"],
                 json.dumps(row["evidence"])))
        for flag in flags:
            conn.execute('INSERT INTO flags (form_id, line_index, field, severity, "check", reason) VALUES (?,?,?,?,?,?)',
                         (form_id, flag["line_index"], flag["field"], flag["severity"], flag["check"], flag["reason"]))
        conn.execute("""UPDATE forms SET status = 'needs_review', extraction_json = ?, extraction_error = NULL,
                        header_json = ?, header_reviewer_action = NULL, header_edited_values_json = NULL
                        WHERE id = ?""", (json.dumps(output), json.dumps(header), form_id))
        log_event(conn, form_id, "extracted")
    return flags


def create_form(db: Database, filename: str, pdf_path: Path, content_hash: str) -> int:
    with db.transaction() as conn:
        cur = conn.execute("INSERT INTO forms (filename, pdf_path, content_hash, uploaded_at, status) "
                           "VALUES (?, ?, ?, ?, 'processing')", (filename, str(pdf_path), content_hash, now()))
        log_event(conn, cur.lastrowid, "uploaded")
        return cur.lastrowid


def mark_extraction_failed(db: Database, form_id: int, error: str) -> None:
    """A form whose extraction failed still goes to the queue, so a person sees it instead of losing it."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM flags WHERE form_id = ?", (form_id,))
        conn.execute("UPDATE forms SET status = 'needs_review', extraction_error = ? WHERE id = ?", (error, form_id))
        conn.execute('INSERT INTO flags (form_id, line_index, field, severity, "check", reason) '
                     "VALUES (?, NULL, NULL, 'high', 'extraction_failed', ?)", (form_id, f"Extraction failed: {error}"))


# ---- values and checks ----

def _dec(value) -> Optional[Decimal]:
    try:
        return None if value is None or value == "" else Decimal(str(value))
    except InvalidOperation:
        return None


def effective_item(row: sqlite3.Row) -> dict:
    """The item's values with the reviewer's edits applied."""
    values = {c: row[c] for c in ("sku", "description", "qty", "unit_price", "amount", "service_start",
                                  "service_end", "billing_terms", "currency", "payment_terms")}
    values.update(json.loads(row["edited_values_json"] or "{}"))
    return values


def effective_header(form: sqlite3.Row) -> dict:
    header = json.loads(form["header_json"] or "{}").get("values", {})
    header.update(json.loads(form["header_edited_values_json"] or "{}"))
    return header


def validate_item_edit(edits: dict, catalog: Catalog) -> Tuple[dict, Dict[str, str]]:
    """Coerce a reviewer's edits: numbers stay numbers, dates are ISO, the SKU is in the catalog."""
    clean, errors = {}, {}
    for field, value in edits.items():
        if field not in EDITABLE:
            errors[field] = "not editable"
        elif field in NUMBER_FIELDS:
            number = _dec(value)
            if number is None or number < 0:
                errors[field] = "must be a non-negative number"
            else:
                clean[field] = float(number)
        elif field in DATE_FIELDS:
            try:
                clean[field] = dt.date.fromisoformat(str(value).strip()).isoformat()
            except ValueError:
                errors[field] = "must be an ISO date (YYYY-MM-DD)"
        elif field == "billing_terms":
            if value not in FREQUENCIES:
                errors[field] = f"must be one of {', '.join(FREQUENCIES)}"
            else:
                clean[field] = value
        elif field == "sku":
            entry = catalog.by_code.get(str(value).strip())
            if entry is None:
                errors[field] = "not a SKU in the catalog"
            else:
                clean["sku"], clean["description"] = entry["sku_code"], entry.get("name")
    return clean, errors


def recompute_amount(original: dict, values: dict, edits: dict) -> dict:
    """When quantity or unit price is edited (and the amount isn't), keep the line's number of billing periods
    and recompute the amount from it: amount = qty x unit price x periods."""
    if "amount" in edits or not ({"qty", "unit_price"} & edits.keys()):
        return values
    q0, u0, a0 = _dec(original["qty"]), _dec(original["unit_price"]), _dec(original["amount"])
    q, u = _dec(values["qty"]), _dec(values["unit_price"])
    if None in (q0, u0, a0, q, u) or q0 * u0 == 0:
        return values
    periods = a0 / (q0 * u0)
    if abs(periods - periods.to_integral_value()) <= RATIO_TOLERANCE:
        values["amount"] = float((q * u * periods.to_integral_value()).quantize(Decimal("0.01")))
    return values


def item_checks(values: dict) -> List[str]:
    """The checker's arithmetic and date rules, re-run on the reviewed values."""
    problems = []
    q, u, a = _dec(values.get("qty")), _dec(values.get("unit_price")), _dec(values.get("amount"))
    if None not in (q, u, a) and q * u:
        ratio = a / (q * u)
        n = ratio.to_integral_value()
        if n < 1 or abs(ratio - n) > RATIO_TOLERANCE:
            problems.append(f"Amount {a} isn't a whole number of periods of quantity x unit price "
                            f"({q} x {u}); check all three")
    try:
        if values.get("service_start") and values.get("service_end") and \
                dt.date.fromisoformat(values["service_start"]) > dt.date.fromisoformat(values["service_end"]):
            problems.append("Service start is after service end")
    except ValueError:
        pass
    return problems


def form_checks(conn: sqlite3.Connection, form: sqlite3.Row) -> List[str]:
    items = [effective_item(r) for r in conn.execute("SELECT * FROM line_items WHERE form_id = ?", (form["id"],))]
    total = sum((_dec(i["amount"]) or Decimal(0)) for i in items)
    grand = _dec(effective_header(form).get("grand_total"))
    if grand is not None and items and total.quantize(Decimal("0.01")) != grand.quantize(Decimal("0.01")):
        return [f"Line amounts add up to {total:,.2f} but the form's grand total is {grand:,.2f}"]
    return []


# ---- reviewer actions ----

def _form(conn: sqlite3.Connection, form_id: int) -> sqlite3.Row:
    form = conn.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
    if form is None:
        raise KeyError(form_id)
    return form


def _editable(form: sqlite3.Row) -> None:
    if form["status"] != "needs_review":
        raise ReviewError(f"form is {form['status']}; only forms in review can be changed")


def review_item(db: Database, catalog: Catalog, form_id: int, item_id: int, action: str,
                edits: Optional[dict] = None) -> dict:
    with db.transaction() as conn:
        form = _form(conn, form_id)
        _editable(form)
        row = conn.execute("SELECT * FROM line_items WHERE id = ? AND form_id = ?", (item_id, form_id)).fetchone()
        if row is None:
            raise KeyError(item_id)
        if action == "accept":
            conn.execute("UPDATE line_items SET reviewer_action = 'accepted' WHERE id = ?", (item_id,))
        elif action == "edit":
            clean, errors = validate_item_edit(edits or {}, catalog)
            if errors:
                raise ReviewError("invalid values", errors)
            original = {c: row[c] for c in ("qty", "unit_price", "amount")}
            merged = dict(json.loads(row["edited_values_json"] or "{}"), **clean)
            values = recompute_amount(original, dict(effective_item(row), **merged), clean)
            if values["amount"] != row["amount"]:
                merged["amount"] = values["amount"]
            if values.get("service_start") and values.get("service_end") and values["service_start"] > values["service_end"]:
                raise ReviewError("invalid values", {"service_end": "must not be before service start"})
            conn.execute("UPDATE line_items SET reviewer_action = 'edited', edited_values_json = ? WHERE id = ?",
                         (json.dumps(merged), item_id))
        else:
            raise ReviewError("action must be accept or edit")
    return get_form(db, form_id)


def review_header(db: Database, form_id: int, action: str, edits: Optional[dict] = None) -> dict:
    with db.transaction() as conn:
        form = _form(conn, form_id)
        _editable(form)
        if action == "accept":
            conn.execute("UPDATE forms SET header_reviewer_action = 'accepted' WHERE id = ?", (form_id,))
        elif action == "edit":
            clean, errors = {}, {}
            for field, value in (edits or {}).items():
                if field not in HEADER_EDITABLE:
                    errors[field] = "not editable"
                elif field == "grand_total":
                    number = _dec(value)
                    if number is None or number < 0:
                        errors[field] = "must be a non-negative number"
                    else:
                        clean[field] = float(number)
                else:
                    try:
                        clean[field] = dt.date.fromisoformat(str(value).strip()).isoformat()
                    except ValueError:
                        errors[field] = "must be an ISO date (YYYY-MM-DD)"
            if errors:
                raise ReviewError("invalid values", errors)
            merged = dict(json.loads(form["header_edited_values_json"] or "{}"), **clean)
            conn.execute("UPDATE forms SET header_reviewer_action = 'edited', header_edited_values_json = ? "
                         "WHERE id = ?", (json.dumps(merged), form_id))
        else:
            raise ReviewError("action must be accept or edit")
    return get_form(db, form_id)


def accept_all_minor(db: Database, form_id: int) -> dict:
    """'Accept all low/medium': accept every unreviewed item (and the header) whose flags are all below high."""
    with db.transaction() as conn:
        form = _form(conn, form_id)
        _editable(form)
        conn.execute("""UPDATE line_items SET reviewer_action = 'accepted'
                        WHERE form_id = ? AND reviewer_action IS NULL AND flag_severity IN ('low', 'medium')""",
                     (form_id,))
        header_severity = F.max_severity(r["severity"] for r in conn.execute(
            "SELECT severity FROM flags WHERE form_id = ? AND line_index IS NULL", (form_id,)))
        if form["header_reviewer_action"] is None and header_severity in ("low", "medium"):
            conn.execute("UPDATE forms SET header_reviewer_action = 'accepted' WHERE id = ?", (form_id,))
    return get_form(db, form_id)


def open_flags(conn: sqlite3.Connection, form_id: int) -> List[sqlite3.Row]:
    """Flags not yet resolved: a flag is resolved once its item (or, for a form-level flag, the header) has been
    accepted or edited by a reviewer."""
    return conn.execute("""
        SELECT f.* FROM flags f
        LEFT JOIN line_items li ON li.form_id = f.form_id AND li.line_index = f.line_index
        JOIN forms fo ON fo.id = f.form_id
        WHERE f.form_id = ? AND CASE WHEN f.line_index IS NULL OR li.id IS NULL
                                     THEN fo.header_reviewer_action IS NULL
                                     ELSE li.reviewer_action IS NULL END""", (form_id,)).fetchall()


def approve(db: Database, form_id: int) -> Tuple[dict, bool]:
    """Approve a form. Only allowed once every high flag is resolved. Approving an approved form again is a
    no-op that still returns the form (so a retried request is harmless). Returns (form, newly_approved)."""
    with db.transaction() as conn:
        form = _form(conn, form_id)
        already = form["status"] == "approved"
        if not already:
            _approve_checked(conn, form)
    return get_form(db, form_id), not already


def _approve_checked(conn: sqlite3.Connection, form: sqlite3.Row) -> None:
    """Raises ReviewError unless every high flag is resolved, then approves inside the caller's transaction."""
    form_id = form["id"]
    _editable(form)
    high = [f for f in open_flags(conn, form_id) if f["severity"] == "high"]
    if high:
        raise ReviewError(f"{len(high)} high-severity flag(s) still open", {"flags": "; ".join(
            f["reason"][:100] for f in high[:3])})
    if form["extraction_json"] is None:
        raise ReviewError("the form has no extraction to approve")
    conn.execute("UPDATE forms SET status = 'approved', approved_at = ? WHERE id = ?", (now(), form_id))
    log_event(conn, form_id, "approved")


def reject(db: Database, form_id: int) -> dict:
    with db.transaction() as conn:
        _editable(_form(conn, form_id))
        conn.execute("UPDATE forms SET status = 'rejected' WHERE id = ?", (form_id,))
    return get_form(db, form_id)


# ---- queries ----

def sync_status(conn: sqlite3.Connection, form_id: int) -> Optional[str]:
    statuses = {r["status"] for r in conn.execute("SELECT status FROM sync_log WHERE form_id = ?", (form_id,))}
    for status in ("failed", "pending", "done"):
        if status in statuses:
            return status
    return None


def _summary(conn: sqlite3.Connection, form: sqlite3.Row) -> dict:
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in open_flags(conn, form["id"]):
        counts[f["severity"]] += 1
    top = next((s for s in ("high", "medium", "low") if counts[s]), None)
    return {"id": form["id"], "filename": form["filename"], "uploaded_at": form["uploaded_at"],
            "status": form["status"], "approved_at": form["approved_at"], "open_flags": counts,
            "top_severity": top, "sync_status": sync_status(conn, form["id"]),
            "extraction_error": form["extraction_error"]}


def list_forms(db: Database, status: Optional[str] = None) -> List[dict]:
    """Queue order: highest open severity first, then oldest upload. status may also be 'sync_failed'."""
    with db.connect() as conn:
        forms = [_summary(conn, f) for f in conn.execute("SELECT * FROM forms ORDER BY uploaded_at, id")]
    if status == "sync_failed":
        forms = [f for f in forms if f["sync_status"] == "failed"]
    elif status:
        forms = [f for f in forms if f["status"] == status]
    return sorted(forms, key=lambda f: -F.SEVERITY_RANK[f["top_severity"]])  # stable: oldest first within a rank


def get_form(db: Database, form_id: int, opened_for_review: bool = False) -> dict:
    with db.connect() as conn:
        form = _form(conn, form_id)
        if opened_for_review and form["status"] == "needs_review" and not has_event(conn, form_id, "review_opened"):
            log_event(conn, form_id, "review_opened")
        open_ids = {f["id"] for f in open_flags(conn, form_id)}
        all_flags = [dict(f, resolved=f["id"] not in open_ids)
                     for f in conn.execute("SELECT * FROM flags WHERE form_id = ? ORDER BY id", (form_id,))]
        items = []
        for row in conn.execute("SELECT * FROM line_items WHERE form_id = ? ORDER BY line_index", (form_id,)):
            values = effective_item(row)
            items.append({
                "id": row["id"], "line_index": row["line_index"], **values,
                "original": {c: row[c] for c in EDITABLE},
                "edited_fields": sorted(json.loads(row["edited_values_json"] or "{}").keys()),
                "flag_severity": row["flag_severity"], "flag_reason": row["flag_reason"],
                "flags": [f for f in all_flags if f["line_index"] == row["line_index"]],
                "source_page": row["source_page"], "source_text": row["source_text"],
                "evidence": json.loads(row["evidence_json"] or "{}"),
                "reviewer_action": row["reviewer_action"], "checks": item_checks(values),
            })
        header = json.loads(form["header_json"] or "{}")
        item_lines = {i["line_index"] for i in items}
        result = _summary(conn, form)
        result.update({
            "header": {"values": effective_header(form), "evidence": header.get("evidence", {}),
                       "edited_fields": sorted(json.loads(form["header_edited_values_json"] or "{}").keys()),
                       "reviewer_action": form["header_reviewer_action"],
                       "flags": [f for f in all_flags if f["line_index"] is None or f["line_index"] not in item_lines]},
            "items": items,
            "form_checks": form_checks(conn, form),
            "can_approve": form["status"] == "needs_review" and form["extraction_json"] is not None
            and not any(not f["resolved"] and f["severity"] == "high" for f in all_flags),
            "sync_errors": [r["last_error"] for r in conn.execute(
                "SELECT DISTINCT last_error FROM sync_log WHERE form_id = ? AND status = 'failed'", (form_id,))],
        })
    return result


def entry_times(db: Database) -> List[float]:
    """Seconds from upload to approval per approved form (the per-form entry-time metric)."""
    with db.connect() as conn:
        rows = conn.execute("""SELECT u.at AS up, a.at AS ap FROM events u JOIN events a
                               ON a.form_id = u.form_id AND a.type = 'approved' WHERE u.type = 'uploaded'""")
        return [(dt.datetime.fromisoformat(r["ap"]) - dt.datetime.fromisoformat(r["up"])).total_seconds() for r in rows]
