"""The checker: planted errors must each be caught, and correct submissions must pass."""
import datetime as dt
import unittest

from ofparser.pdf import add_months, dates_in
from ofparser.schema import Ambiguity, InferredDate
from ofparser.validator import active_issues, validate
from tests.helpers import context, submission_from_gold

FORM = "of-0037"  # 4 items, quantities 1 and 3, 3-year term priced yearly


def checks(sub, ctx=None, severity=None):
    issues = active_issues(validate(sub, ctx or context(FORM)), sub)
    return {i.check for i in issues if severity is None or i.severity == severity}


class CheckerTest(unittest.TestCase):
    def setUp(self):
        self.sub = submission_from_gold(FORM)

    def test_correct_submission_passes(self):
        self.assertEqual(checks(self.sub), set())

    def test_all_ground_truth_passes(self):
        for n in range(1, 51):
            form = f"of-{n:04d}"
            self.assertEqual(checks(submission_from_gold(form), context(form)), set(), form)

    def test_fake_amount_is_a_hard_error(self):
        self.sub.contract_items[0].total_listed_value = 123456.78
        self.assertIn("ungrounded_amount", checks(self.sub, severity="error"))

    def test_broken_line_math_is_flagged(self):
        # a real document number, but from another line: grounded, yet the price no longer fits the total
        self.sub.contract_items[0].unit_price = self.sub.contract_items[2].unit_price
        self.assertIn("price_ratio_not_integer", checks(self.sub, severity="warning"))

    def test_null_quantity_is_flagged(self):
        self.sub.contract_items[1].quantity = None
        self.assertIn("missing_value", checks(self.sub, severity="warning"))

    def test_null_quantity_flagged_as_ambiguous_is_accepted(self):
        from ofparser.schema import Ambiguity
        self.sub.contract_items[1].quantity = None
        self.sub.ambiguities.append(Ambiguity(item_index=1, field="quantity", candidates=["1", "3"], reason="x"))
        self.assertNotIn("missing_value", checks(self.sub))

    def test_unknown_sku_is_a_hard_error(self):
        self.sub.contract_items[0].sku_code = "NOT_A_REAL_SKU"
        self.assertIn("sku_not_in_catalog", checks(self.sub, severity="error"))

    def test_reversed_dates_are_a_hard_error(self):
        item = self.sub.contract_items[0]
        item.service_start_date, item.service_end_date = item.service_end_date, item.service_start_date
        self.assertIn("date_order", checks(self.sub, severity="error"))

    def test_overrides_silence_warnings_but_not_errors(self):
        from ofparser.schema import Override
        self.sub.contract_items[1].quantity = None
        self.sub.contract_items[0].sku_code = "NOT_A_REAL_SKU"
        self.sub.overrides = [Override(check="missing_value", item_index=1, reason="catalog says null"),
                              Override(check="sku_not_in_catalog", item_index=0, reason="trust me")]
        self.assertEqual(checks(self.sub), {"sku_not_in_catalog"})

    def test_excluded_sku_conflict_is_a_warning_not_a_removal(self):
        self.sub.explicitly_excluded_skus = [self.sub.contract_items[0].sku_code]
        self.assertIn("excluded_conflict", checks(self.sub, severity="warning"))

    def test_bad_ambiguity_entries_are_rejected(self):
        from ofparser.schema import Ambiguity
        self.sub.ambiguities.append(Ambiguity(item_index=None, field="service_start_date",
                                              candidates=["a", "b"], reason="x"))
        self.assertIn("bad_ambiguity", checks(self.sub, severity="error"))

    def test_scanned_pdf_skips_grounding_and_says_so(self):
        self.sub.contract_items[0].total_listed_value = 123456.78
        issues = validate(self.sub, context(FORM, text_layer=False))
        self.assertNotIn("ungrounded_amount", {i.check for i in issues})
        self.assertIn("no_text_layer", {i.check for i in issues if i.severity == "note"})

    def test_null_header_date_is_flagged(self):
        self.sub.order_form.effective_date = None
        self.assertIn("missing_value", checks(self.sub, severity="warning"))

    def test_null_header_date_flagged_as_ambiguous_is_accepted(self):
        self.sub.order_form.effective_date = None
        self.sub.ambiguities.append(Ambiguity(item_index=None, field="effective_date",
                                              candidates=["2024-06-04", "2024-04-06"], reason="x"))
        self.assertEqual(checks(self.sub), set())


class DateGroundingTest(unittest.TestCase):
    def setUp(self):
        self.sub = submission_from_gold(FORM)
        self.ctx = context(FORM)
        self.item = self.sub.contract_items[0]
        start = dt.date.fromisoformat(self.item.service_start_date)
        # a date that follows from the printed start date but is not itself printed
        self.derived = add_months(start, 6)
        self.assertNotIn(self.derived, self.ctx.doc_dates)

    def test_made_up_date_is_sent_back(self):
        self.item.service_end_date = "2031-02-17"
        self.assertIn("date_not_in_document", checks(self.sub, self.ctx, severity="warning"))

    def test_made_up_header_date_is_sent_back(self):
        self.sub.order_form.contract_signed_date_buying_company = "2031-02-17"
        self.assertIn("date_not_in_document", checks(self.sub, self.ctx, severity="warning"))

    def test_inferred_date_with_correct_calculation_passes(self):
        self.item.service_end_date = self.derived.isoformat()
        self.sub.inferred_dates = [InferredDate(item_index=0, field="service_end_date",
                                                from_date=self.item.service_start_date, add_months=6,
                                                explanation="start + 6-month term")]
        # (the shorter term breaks this line's price math, which is a separate check)
        self.assertNotIn("date_not_in_document", checks(self.sub, self.ctx))

    def test_inferred_date_with_wrong_calculation_is_sent_back(self):
        self.item.service_end_date = self.derived.isoformat()
        self.sub.inferred_dates = [InferredDate(item_index=0, field="service_end_date",
                                                from_date=self.item.service_start_date, add_months=6, add_days=-1,
                                                explanation="off by one")]
        self.assertIn("date_not_in_document", checks(self.sub, self.ctx, severity="warning"))

    def test_inferred_date_must_start_from_a_printed_date(self):
        self.item.service_end_date = "2031-08-17"
        self.sub.inferred_dates = [InferredDate(item_index=0, field="service_end_date", from_date="2031-02-17",
                                                add_months=6, explanation="from an unprinted date")]
        self.assertIn("date_not_in_document", checks(self.sub, self.ctx, severity="warning"))

    def test_inferred_entry_on_non_date_field_is_rejected(self):
        self.sub.inferred_dates = [InferredDate(item_index=0, field="payment_terms",
                                                from_date=self.item.service_start_date, explanation="x")]
        self.assertIn("bad_inferred_date", checks(self.sub, self.ctx, severity="error"))

    def test_scanned_pdf_skips_date_grounding(self):
        self.item.service_end_date = "2031-02-17"
        self.assertNotIn("date_not_in_document", checks(self.sub, context(FORM, text_layer=False)))


class DatesInTest(unittest.TestCase):
    def test_common_formats_are_recognised(self):
        text = ("Effective 2025-08-04. Signed Aug 08, 2025 and 8th of August 2025. Start 07 Jun 2024, "
                "end 12-Dec-2023, renewal Sept. 3 2024, due 2025/01/15.")
        self.assertTrue({dt.date(2025, 8, 4), dt.date(2025, 8, 8), dt.date(2024, 6, 7), dt.date(2023, 12, 12),
                         dt.date(2024, 9, 3), dt.date(2025, 1, 15)} <= dates_in(text))

    def test_day_month_swap_counts_as_present_both_ways(self):
        self.assertEqual(dates_in("06/04/2024"), {dt.date(2024, 6, 4), dt.date(2024, 4, 6)})
        self.assertEqual(dates_in("31/12/24"), {dt.date(2024, 12, 31)})  # only one reading is a real date

    def test_value_matters_not_the_quote(self):
        # the same date in a different format still counts as present
        self.assertIn(dt.date(2025, 8, 7), dates_in("Start Date: 08/07/2025"))
        self.assertIn(dt.date(2025, 8, 7), dates_in("August 7, 2025"))


if __name__ == "__main__":
    unittest.main()
