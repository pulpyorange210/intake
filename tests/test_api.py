"""Review API and Slack alerts end to end, with recorded extractions (no API key) and mocked Sheets/Slack."""
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings
from server.retry import HTTPStatusError
from server.slack import alert_payload
from tests.test_sync import FakeSheet

ROOT = Path(__file__).resolve().parent.parent
PDFS = ROOT / "synthetic_order_form_dataset_50" / "pdfs"
HAS_PDFTOTEXT = shutil.which("pdftotext") is not None


class FakeSlack:
    def __init__(self, fail_with=None, failures=0):
        self.payloads, self.fail_with, self.failures = [], fail_with, failures

    def post(self, payload):
        if self.failures:
            self.failures -= 1
            raise self.fail_with
        self.payloads.append(payload)


def settings(tmp: Path) -> Settings:
    return Settings(data_dir=tmp, db_path=tmp / "intake.db",
                    catalog_path=ROOT / "synthetic_order_form_dataset_50" / "sku_catalog.json",
                    extractor="replay", cassettes_dir=ROOT / "evals" / "cassettes",
                    google_service_account_json=None, sheet_id=None, slack_webhook_url=None,
                    review_ui_base_url="http://review.test")


@unittest.skipUnless(HAS_PDFTOTEXT, "needs poppler's pdftotext")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sheet, self.slack = FakeSheet(), FakeSlack()
        self.app = create_app(settings(Path(self.tmp.name)), sheets=self.sheet, notifier=self.slack)
        self.client = TestClient(self.app)
        self.client.__enter__()
        # The retry backoff sleeps for real inside the worker; keep tests fast.
        import server.slack as slack_module
        self._orig_backoff = slack_module.retry.backoff
        slack_module.retry.backoff = lambda attempt, rng=None: 0

    def tearDown(self):
        import server.slack as slack_module
        slack_module.retry.backoff = self._orig_backoff
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def drain(self):
        self.client.portal.call(self.app.state.worker.drain)

    def upload(self, form: str) -> int:
        with (PDFS / f"{form}.pdf").open("rb") as f:
            r = self.client.post("/forms?wait=true", files={"file": (f"{form}.pdf", f, "application/pdf")})
        self.assertEqual(r.status_code, 201, r.text)
        self.drain()
        return r.json()["form_id"]

    # ---- foundations ----
    def test_upload_stores_items_flags_and_sources(self):
        form_id = self.upload("of-0001")
        form = self.client.get(f"/forms/{form_id}?review=true").json()
        self.assertEqual(form["status"], "needs_review")
        self.assertGreater(len(form["items"]), 0)
        item = form["items"][0]
        self.assertIsNotNone(item["sku"])
        self.assertEqual(item["source_page"], 1)
        self.assertIn("amount", item["evidence"])
        self.assertEqual(self.client.get(f"/forms/{form_id}/pdf").headers["content-type"], "application/pdf")

    def test_queue_puts_high_severity_first(self):
        clean = self.upload("of-0001")
        high = self.upload("of-0032")  # effective date 06/04/2024 reads two ways -> left blank -> high
        queue = self.client.get("/forms?status=needs_review").json()
        self.assertEqual(queue[0]["id"], high)
        self.assertEqual(queue[0]["top_severity"], "high")
        self.assertIn(clean, [f["id"] for f in queue])

    def test_approve_blocked_until_high_flag_resolved(self):
        form_id = self.upload("of-0032")
        r = self.client.post(f"/forms/{form_id}/approve")
        self.assertEqual(r.status_code, 409)
        self.assertIn("high-severity", r.json()["detail"])
        self.assertFalse(self.client.get(f"/forms/{form_id}").json()["can_approve"])
        r = self.client.patch(f"/forms/{form_id}/header", json={"action": "edit",
                                                                 "values": {"effective_date": "2024-06-04"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["can_approve"])
        self.assertEqual(self.client.post(f"/forms/{form_id}/approve").status_code, 200)

    def test_edit_validates_and_recomputes(self):
        form_id = self.upload("of-0032")
        item = self.client.get(f"/forms/{form_id}").json()["items"][0]
        bad = self.client.patch(f"/forms/{form_id}/items/{item['id']}",
                                json={"action": "edit", "values": {"qty": "two", "service_end": "03/07/2025"}})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(set(bad.json()["fields"]), {"qty", "service_end"})
        r = self.client.patch(f"/forms/{form_id}/items/{item['id']}", json={"action": "edit", "values": {"qty": 2}})
        edited = r.json()["items"][0]
        self.assertEqual(edited["qty"], 2.0)
        self.assertAlmostEqual(edited["amount"], item["amount"] * 2, places=2)  # periods kept, amount doubled
        self.assertEqual(edited["checks"], [])
        self.assertTrue(r.json()["form_checks"])  # grand total no longer matches the line amounts

    def test_approve_syncs_reviewed_values_once(self):
        form_id = self.upload("of-0001")
        form = self.client.get(f"/forms/{form_id}").json()
        item = form["items"][0]
        self.client.patch(f"/forms/{form_id}/items/{item['id']}",
                          json={"action": "edit", "values": {"unit_price": 1234.5}})
        self.client.post(f"/forms/{form_id}/accept-minor")
        self.assertEqual(self.client.post(f"/forms/{form_id}/approve").status_code, 200)
        self.drain()
        self.client.post(f"/forms/{form_id}/approve")  # approving again
        self.drain()
        self.assertEqual(len(self.sheet.rows), len(form["items"]))
        row = next(r for r in self.sheet.rows if r[3] == item["line_index"])
        self.assertEqual(row[7], 1234.5)
        self.assertEqual(row[-1], "TRUE")
        self.assertEqual(self.client.get(f"/forms/{form_id}").json()["sync_status"], "done")

    # ---- Phase 2: Slack ----
    def test_clean_form_sends_no_alert(self):
        clean = next(f for f in ("of-0001", "of-0003", "of-0004", "of-0006") if not self._flags_of(f))
        self.upload(clean)
        self.assertEqual(self.slack.payloads, [])

    def _flags_of(self, form):
        from ofparser import cassette
        from ofparser.catalog import Catalog
        from server.flags import derive_flags
        catalog = Catalog.load(ROOT / "synthetic_order_form_dataset_50" / "sku_catalog.json")
        out = cassette.replay(cassette.load(ROOT / "evals" / "cassettes" / f"{form}.json"), PDFS / f"{form}.pdf", catalog)
        return derive_flags(out)

    def test_flagged_form_alerts_once_even_if_reextracted(self):
        form_id = self.upload("of-0032")
        self.assertEqual(len(self.slack.payloads), 1)
        self.client.post(f"/forms/{form_id}/extract")
        self.app.state.worker.extraction_pool.shutdown(wait=True)
        self.drain()
        self.assertEqual(len(self.slack.payloads), 1)
        self.assertTrue(self.slack.payloads[0]["text"].startswith("🔴"))

    def test_slack_500_does_not_block_the_queue(self):
        self.slack.fail_with, self.slack.failures = HTTPStatusError(500, "slack down"), 99
        form_id = self.upload("of-0032")
        queue = self.client.get("/forms?status=needs_review").json()
        self.assertEqual([f["id"] for f in queue], [form_id])
        self.assertEqual(self.slack.payloads, [])


class SlackPayloadTests(unittest.TestCase):
    def flags(self, *severities):
        return [{"severity": s, "reason": f"{s} reason {i}"} for i, s in enumerate(severities)]

    def test_block_kit_shape(self):
        payload = alert_payload("of-0032.pdf", 7, self.flags("high", "high", "medium"), "https://review.example")
        self.assertEqual(set(payload), {"text", "blocks"})
        header, reasons, actions = payload["blocks"]
        self.assertEqual(header["type"], "section")
        self.assertEqual(header["text"]["type"], "mrkdwn")
        self.assertIn("*of-0032.pdf*", header["text"]["text"])
        self.assertIn("2 high · 1 medium", header["text"]["text"])
        self.assertTrue(header["text"]["text"].startswith("🔴"))
        self.assertIn("high reason 0", reasons["text"]["text"])
        self.assertNotIn("medium reason", reasons["text"]["text"])
        button = actions["elements"][0]
        self.assertEqual(actions["type"], "actions")
        self.assertEqual(button["type"], "button")
        self.assertEqual(button["url"], "https://review.example/forms/7")

    def test_at_most_three_reasons_then_more(self):
        payload = alert_payload("f.pdf", 1, self.flags(*["high"] * 5), "http://x")
        text = payload["blocks"][1]["text"]["text"]
        self.assertEqual(text.count("•"), 3)
        self.assertIn("+2 more", text)

    def test_only_medium_or_low_is_yellow_with_no_reasons_block(self):
        payload = alert_payload("f.pdf", 1, self.flags("medium", "low"), "http://x")
        self.assertTrue(payload["text"].startswith("🟡"))
        self.assertEqual([b["type"] for b in payload["blocks"]], ["section", "actions"])

    def test_mrkdwn_is_escaped(self):
        payload = alert_payload("a<b>&c.pdf", 1, self.flags("high"), "http://x")
        self.assertIn("a&lt;b&gt;&amp;c.pdf", payload["blocks"][0]["text"]["text"])


if __name__ == "__main__":
    unittest.main()
