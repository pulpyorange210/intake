import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

import run as evals_run  # noqa: E402


class ThresholdTests(unittest.TestCase):
    THRESHOLDS = {"wrong_values": 0, "wrong_sku_matches": 0, "line_item_recall": 1.0, "no_review_forms_min": 47,
                  "cost_per_form_max_usd": 0.25}
    GOOD = {"wrong_values": 0, "wrong_sku_matches": 0, "line_item_recall": 1.0, "no_review_forms": 49,
            "cost_per_form_usd": 0.17}

    def test_passing_summary(self):
        self.assertEqual(evals_run.check_thresholds(self.GOOD, self.THRESHOLDS), [])

    def test_each_direction_fails(self):
        cases = {"wrong_values": 1, "line_item_recall": 0.99, "no_review_forms": 46, "cost_per_form_usd": 0.26}
        for metric, value in cases.items():
            failures = evals_run.check_thresholds(dict(self.GOOD, **{metric: value}), self.THRESHOLDS)
            self.assertEqual(len(failures), 1, metric)
            self.assertIn(metric, failures[0])

    def test_thresholds_file_parses(self):
        thresholds = evals_run.load_thresholds(evals_run.EVALS / "thresholds.yaml")
        self.assertEqual(thresholds["wrong_values"], 0)
        self.assertEqual(thresholds["cost_per_form_max_usd"], 0.25)


class ScoringTests(unittest.TestCase):
    def test_numbers_and_dates_are_normalised(self):
        self.assertEqual(evals_run.normalize("quantity", 1), evals_run.normalize("quantity", "1.0"))
        self.assertEqual(evals_run.normalize("unit_price", 30180.26), evals_run.normalize("unit_price", "30180.260"))
        self.assertEqual(evals_run.normalize("service_start_date", " 2025-08-07"),
                         evals_run.normalize("service_start_date", "2025-08-07"))

    def test_flagged_value_is_not_wrong(self):
        item = {"sku_code": "A", "total_listed_value": 100.0, "currency": "USD",
                "invoicing_frequency": {"value": "one-time", "ambiguous": True, "alternatives": ["yearly"]}}
        expected = {"contract_items": [{"sku_code": "A", "total_listed_value": 100.0, "currency": "USD",
                                        "invoicing_frequency": "yearly"}]}
        result = evals_run.score_form("f", {"contract_items": [item], "order_form": {}}, expected)
        self.assertEqual(result["wrong_values"], [])
        self.assertEqual(result["flagged_values"], 1)

    def test_regression_names_form_and_field(self):
        base = {"forms": [{"form": "f", "wrong_values": [], "missing_values": [], "missed_items": [],
                           "wrong_skus": [], "needs_review": False}]}
        now = [{"form": "f", "wrong_values": [{"where": "A", "field": "unit_price", "got": 2, "expected": 1}],
                "missing_values": [], "missed_items": [], "wrong_skus": [], "needs_review": False}]
        [line] = evals_run.regressions(now, base)
        self.assertIn("f: A unit_price", line)


if __name__ == "__main__":
    unittest.main()
