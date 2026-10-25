"""Phase 1: idempotency keys and the Sheets sync (mocked Sheets clients, no network)."""
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from server import forms as R
from server.db import Database
from server.idempotency import canonical_json, line_key
from server.retry import HTTPStatusError
from server.sheets import CsvSheet, sync_form


class FakeSheet:
    """In-memory sheet. `script` lists what each append call does: 'ok', an exception to raise before
    anything lands, or ('lost', exc) to land the rows and then raise (the response never arrived)."""

    def __init__(self, script=(), read_script=()):
        self.rows, self.script, self.read_script = [], list(script), list(read_script)
        self.appends = 0

    def read_keys(self):
        if self.read_script:
            step = self.read_script.pop(0)
            if isinstance(step, Exception):
                raise step
        return {r[0] for r in self.rows}

    def append(self, rows):
        self.appends += 1
        step = self.script.pop(0) if self.script else "ok"
        if isinstance(step, tuple):
            self.rows += rows
            raise step[1]
        if isinstance(step, Exception):
            raise step
        self.rows += rows


def make_approved_form(db, lines=2, content_hash="h" * 64):
    form_id = R.create_form(db, "of-test.pdf", Path("/nonexistent.pdf"), content_hash)
    with db.transaction() as conn:
        for i in range(lines):
            conn.execute("""INSERT INTO line_items (form_id, line_index, sku, description, qty, unit_price, amount,
                            service_start, service_end, billing_terms) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (form_id, i, f"SKU_{i}", f"Product {i}", 1, 100.0 + i, 1200.0 + 12 * i, "2025-01-01",
                          "2025-12-31", "monthly"))
        conn.execute("UPDATE forms SET status = 'needs_review', extraction_json = '{}', header_json = '{}' "
                     "WHERE id = ?", (form_id,))
    R.approve(db, form_id)
    return form_id


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "intake.db")
        self.sleeps = []

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self, form_id, client):
        return sync_form(self.db, form_id, client, sleep=self.sleeps.append)

    def log(self, form_id):
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM sync_log WHERE form_id = ?", (form_id,))]


class IdempotencyKeyTests(unittest.TestCase):
    def test_key_order_does_not_matter(self):
        self.assertEqual(canonical_json({"a": 1, "b": 2}), canonical_json({"b": 2, "a": 1}))

    def test_one_and_one_point_zero_are_the_same(self):
        self.assertEqual(line_key("h", 0, {"qty": 1}), line_key("h", 0, {"qty": 1.0}))
        self.assertEqual(line_key("h", 0, {"unit_price": 30180.26}), line_key("h", 0, {"unit_price": 30180.260}))

    def test_trailing_spaces_do_not_matter(self):
        self.assertEqual(line_key("h", 0, {"sku": "ABC "}), line_key("h", 0, {"sku": "ABC"}))

    def test_no_whitespace_in_canonical_form(self):
        self.assertEqual(canonical_json({"b": [1, "x "], "a": None}), '{"a":null,"b":["1.000000","x"]}')

    def test_edited_value_changes_the_key(self):
        self.assertNotEqual(line_key("h", 0, {"qty": 1}), line_key("h", 0, {"qty": 2}))
        self.assertNotEqual(line_key("h", 0, {"qty": 1}), line_key("h", 1, {"qty": 1}))
        self.assertNotEqual(line_key("h", 0, {"qty": 1}), line_key("g", 0, {"qty": 1}))


class SyncTests(Base):
    def test_one_row_per_line_item(self):
        form_id = make_approved_form(self.db, lines=3)
        sheet = FakeSheet()
        self.assertEqual(self.sync(form_id, sheet), "done")
        self.assertEqual(len(sheet.rows), 3)
        self.assertTrue(all(r["status"] == "done" and r["attempts"] == 1 for r in self.log(form_id)))

    def test_syncing_twice_does_not_duplicate(self):
        form_id = make_approved_form(self.db)
        sheet = FakeSheet()
        self.sync(form_id, sheet)
        self.sync(form_id, sheet)
        self.assertEqual(len(sheet.rows), 2)
        self.assertEqual(sheet.appends, 1)

    def test_approving_twice_does_not_duplicate(self):
        form_id = make_approved_form(self.db)
        sheet = FakeSheet()
        self.sync(form_id, sheet)
        _, newly = R.approve(self.db, form_id)
        self.assertFalse(newly)
        self.sync(form_id, sheet)
        self.assertEqual(len(sheet.rows), 2)

    def test_lost_response_after_append_is_not_duplicated(self):
        """The append lands, then the call raises before the response returns; the retry re-reads column A."""
        form_id = make_approved_form(self.db)
        sheet = FakeSheet(script=[("lost", httpx.ReadTimeout("response lost"))])
        self.assertEqual(self.sync(form_id, sheet), "done")
        self.assertEqual(len(sheet.rows), 2)
        self.assertEqual(sheet.appends, 1)
        self.assertEqual(len(self.sleeps), 1)

    def test_crash_before_recording_is_recovered(self):
        """Rows landed but the process died before marking them done: the next sync marks them done, no append."""
        form_id = make_approved_form(self.db)
        sheet = FakeSheet()
        self.sync(form_id, sheet)
        with self.db.transaction() as conn:
            conn.execute("UPDATE sync_log SET status = 'pending' WHERE form_id = ?", (form_id,))
        self.assertEqual(self.sync(form_id, sheet), "done")
        self.assertEqual(sheet.appends, 1)
        self.assertTrue(all(r["status"] == "done" for r in self.log(form_id)))

    def test_429_twice_then_success(self):
        form_id = make_approved_form(self.db)
        sheet = FakeSheet(script=[HTTPStatusError(429), HTTPStatusError(429)])
        self.assertEqual(self.sync(form_id, sheet), "done")
        self.assertEqual(len(sheet.rows), 2)
        self.assertEqual([r["attempts"] for r in self.log(form_id)], [3, 3])
        self.assertEqual(len(self.sleeps), 2)
        self.assertTrue(all(0 <= s <= 30 for s in self.sleeps))

    def test_5xx_on_read_is_retried(self):
        form_id = make_approved_form(self.db)
        sheet = FakeSheet(read_script=[HTTPStatusError(503)])
        self.assertEqual(self.sync(form_id, sheet), "done")
        self.assertEqual(len(sheet.rows), 2)

    def test_other_4xx_fails_without_retry(self):
        form_id = make_approved_form(self.db)
        sheet = FakeSheet(script=[HTTPStatusError(403, "caller does not have permission")])
        self.assertEqual(self.sync(form_id, sheet), "failed")
        self.assertEqual(self.sleeps, [])
        log = self.log(form_id)
        self.assertTrue(all(r["status"] == "failed" and r["attempts"] == 1 for r in log))
        self.assertIn("403", log[0]["last_error"])
        self.assertEqual(R.list_forms(self.db, "sync_failed")[0]["id"], form_id)

    def test_gives_up_after_five_attempts_then_manual_retry_works(self):
        form_id = make_approved_form(self.db)
        sheet = FakeSheet(script=[HTTPStatusError(500)] * 5)
        self.assertEqual(self.sync(form_id, sheet), "failed")
        self.assertEqual(len(self.sleeps), 4)
        self.assertEqual(self.sync(form_id, sheet), "done")  # the manual retry
        self.assertEqual(len(sheet.rows), 2)

    def test_edited_value_gets_a_new_row(self):
        """A deliberate edit is a new key. (Edits happen before approval; this re-opens the form to simulate a
        corrected re-approval.)"""
        form_id = make_approved_form(self.db, lines=1)
        sheet = FakeSheet()
        self.sync(form_id, sheet)
        with self.db.transaction() as conn:
            conn.execute("UPDATE line_items SET edited_values_json = ? WHERE form_id = ?",
                         (json.dumps({"qty": 2}), form_id))
        self.sync(form_id, sheet)
        self.assertEqual(len(sheet.rows), 2)

    def test_csv_sheet_round_trip(self):
        form_id = make_approved_form(self.db)
        sheet = CsvSheet(Path(self.tmp.name) / "sheet.csv")
        self.sync(form_id, sheet)
        self.sync(form_id, sheet)
        lines = (Path(self.tmp.name) / "sheet.csv").read_text().splitlines()
        self.assertEqual(len(lines), 3)  # header + 2 rows
        self.assertTrue(lines[0].startswith("idempotency_key,form_id,filename"))


if __name__ == "__main__":
    unittest.main()
