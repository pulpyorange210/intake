"""Frequency fallback: stated billing wins, 6-month periods work, ambiguity is flagged next to the value."""
import unittest

from ofparser.postprocess import infer_frequency
from ofparser.schema import ContractItem
from ofparser.catalog import Catalog
from ofparser.postprocess import build_output
from ofparser.schema import Submission
from tests.helpers import CATALOG


def item(total, qty, unit, start, end, stated=None):
    return ContractItem(sku_code="SANDBOX", source_row="", currency="USD", total_listed_value=total, quantity=qty,
                        unit_price=unit, unit_price_period=None, period_amounts=None, discount=None,
                        service_start_date=start, service_end_date=end, invoicing_schedule_type=None,
                        invoicing_frequency=stated, payment_terms=None, special_notes=None, evidence={})


def submission(it, **header):
    dates = {"effective_date": "2025-01-01", "contract_signed_date_buying_company": "2025-01-01",
             "contract_signed_date_selling_company": "2025-01-01", **header}
    return Submission(order_form={"customer_name": None, "vendor_name": None, "currency": None, "grand_total": None,
                                  "grand_total_label": None, "evidence": {}, **dates},
                      contract_items=[it], explicitly_excluded_skus=[])


def output_frequency(it):
    return build_output(submission(it), CATALOG, [])["contract_items"][0]["invoicing_frequency"]


class FrequencyTest(unittest.TestCase):
    def test_stated_billing_beats_price_math(self):
        # priced per month (12 x 100 over a year) but the document says billed annually
        f = output_frequency(item(1200, 1, 100, "2025-01-01", "2025-12-31", stated="yearly"))
        self.assertEqual((f["value"], f["source"], f["ambiguous"]), ("yearly", "stated", False))

    def test_monthly_quarterly_and_six_monthly_periods(self):
        self.assertEqual(infer_frequency(item(1200, 1, 100, "2025-01-01", "2025-12-31"))["value"], "monthly")
        self.assertEqual(infer_frequency(item(400, 1, 100, "2025-01-01", "2025-12-31"))["value"], "quarterly")
        self.assertEqual(infer_frequency(item(200, 1, 100, "2025-01-01", "2025-12-31"))["value"], "biannually")
        self.assertEqual(infer_frequency(item(600, 1, 100, "2025-01-01", "2027-12-31"))["value"], "biannually")

    def test_single_price_multi_year_is_one_time_unflagged(self):
        f = infer_frequency(item(100, 1, 100, "2025-01-01", "2027-12-31"))
        self.assertEqual((f["value"], f["ambiguous"]), ("one-time", False))

    def test_single_price_one_period_term_is_flagged_next_to_value(self):
        f = infer_frequency(item(100, 1, 100, "2025-01-01", "2025-12-31"))
        self.assertEqual((f["value"], f["ambiguous"], f["alternatives"]), ("one-time", True, ["yearly"]))
        self.assertIn("One invoice for the full amount", f["reason"])
        f6 = infer_frequency(item(100, 1, 100, "2025-01-01", "2025-06-30"))
        self.assertEqual(f6["alternatives"], ["biannually"])

    def test_non_standard_period_is_not_guessed(self):
        f = infer_frequency(item(500, 1, 100, "2025-01-01", "2025-12-31"))  # 5 periods in 12 months
        self.assertIsNone(f["value"])


class SkuBlockTest(unittest.TestCase):
    def test_plain_sku_is_an_unflagged_block(self):
        out = build_output(submission(item(100, 1, 100, "2025-01-01", "2025-12-31")), CATALOG, [])
        self.assertEqual(out["contract_items"][0]["sku_code"],
                         {"value": "SANDBOX", "ambiguous": False, "alternatives": [], "reason": None})
        self.assertFalse(out["needs_review"])

    def test_ambiguous_sku_keeps_the_likely_code_flags_it_and_needs_review(self):
        from ofparser.schema import Ambiguity
        sub = submission(item(100, 1, 100, "2025-01-01", "2025-12-31"))
        sub.ambiguities = [Ambiguity(item_index=0, field="sku_code", candidates=["SANDBOX", "COPILOT"],
                                     likely="SANDBOX", reason="name fits both")]
        out = build_output(sub, CATALOG, [])
        sku = out["contract_items"][0]["sku_code"]
        self.assertEqual((sku["value"], sku["ambiguous"], sku["alternatives"]), ("SANDBOX", True, ["COPILOT"]))
        self.assertTrue(out["needs_review"])
        self.assertNotIn("sku_code", out["contract_items"][0]["ambiguous_fields"])


class MissingFieldsTest(unittest.TestCase):
    def test_complete_output_is_not_flagged(self):
        # null schedule type / special notes and a label-ambiguous frequency are blank or flagged by design
        out = build_output(submission(item(100, 1, 100, "2025-01-01", "2025-12-31")), CATALOG, [])
        self.assertTrue(out["contract_items"][0]["invoicing_frequency"]["ambiguous"])
        self.assertFalse(out["needs_review"])
        self.assertEqual(out["contract_items"][0]["missing_fields"], {})

    def test_blank_total_is_flagged_even_with_a_reason(self):
        from ofparser.schema import Override
        sub = submission(item(None, 1, 100, "2025-01-01", "2025-12-31"))
        sub.overrides = [Override(check="missing_value", item_index=0, reason="no total printed")]
        out = build_output(sub, CATALOG, [])
        self.assertTrue(out["needs_review"])
        missing = out["contract_items"][0]["missing_fields"]["total_listed_value"]
        self.assertEqual(missing["status"], "not_found")
        self.assertIn("no total printed", missing["reason"])

    def test_blank_without_a_reason_says_so(self):
        out = build_output(submission(item(100, None, 100, "2025-01-01", None)), CATALOG, [])
        self.assertTrue(out["needs_review"])
        self.assertEqual(set(out["contract_items"][0]["missing_fields"]), {"quantity", "service_end_date"})
        self.assertIn("no reason given", out["contract_items"][0]["missing_fields"]["quantity"]["reason"])

    def test_ambiguous_blank_header_date_is_flagged_with_its_reason(self):
        from ofparser.schema import Ambiguity
        sub = submission(item(100, 1, 100, "2025-01-01", "2025-12-31"), effective_date=None)
        sub.ambiguities = [Ambiguity(item_index=None, field="effective_date", candidates=["a", "b"],
                                     reason="MM/DD vs DD/MM")]
        out = build_output(sub, CATALOG, [])
        self.assertTrue(out["needs_review"])
        missing = out["order_form"]["missing_fields"]["effective_date"]
        self.assertEqual(missing["status"], "ambiguous")
        self.assertIn("MM/DD vs DD/MM", missing["reason"])

    def test_overridden_unprinted_date_is_flagged(self):
        from ofparser.schema import Override
        sub = submission(item(100, 1, 100, "2025-01-01", "2025-12-31"))
        sub.overrides = [Override(check="date_not_in_document", item_index=0, reason="trust me")]
        self.assertTrue(build_output(sub, CATALOG, [])["needs_review"])


if __name__ == "__main__":
    unittest.main()
