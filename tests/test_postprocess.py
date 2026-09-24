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


def output_frequency(it):
    sub = Submission(order_form={"customer_name": None, "vendor_name": None, "effective_date": None,
                                 "contract_signed_date_buying_company": None,
                                 "contract_signed_date_selling_company": None, "currency": None,
                                 "grand_total": None, "grand_total_label": None, "evidence": {}},
                     contract_items=[it], explicitly_excluded_skus=[])
    return build_output(sub, CATALOG, [])["contract_items"][0]["invoicing_frequency"]


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


if __name__ == "__main__":
    unittest.main()
