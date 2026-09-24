"""The checker: planted errors must each be caught, and correct submissions must pass."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
