"""The grader itself: ground truth scored as a prediction must be perfect, and a one-cent change must
fail exactly one field."""
import json
import tempfile
import unittest
from pathlib import Path

from eval import score_run
from tests.helpers import DATASET, prediction_from_gold

FORMS = sorted(p.stem for p in (DATASET / "ground_truth").glob("*.json"))


def run_with(predictions: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "outputs"
        out.mkdir()
        for form, pred in predictions.items():
            (out / f"{form}.json").write_text(json.dumps(pred))
        result, _ = score_run(Path(tmp), DATASET)
    return result


def failure_count(result: dict) -> int:
    return sum(len(v) for v in result["failures"].values())


class GraderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.perfect = {form: prediction_from_gold(form) for form in FORMS}

    def test_ground_truth_scores_perfectly(self):
        result = run_with(self.perfect)
        self.assertEqual(result["forms"], len(FORMS))
        self.assertEqual((result["items"]["precision"], result["items"]["recall"]), (1.0, 1.0))
        for field, r in result["fields"].items():
            self.assertEqual(r["overall"], 1.0, field)
        self.assertEqual(result["forms_fully_correct"], len(FORMS))
        self.assertEqual(failure_count(result), 0)

    def test_one_cent_change_fails_exactly_one_field(self):
        preds = json.loads(json.dumps(self.perfect))
        preds["of-0037"]["contract_items"][2]["unit_price"] += 0.01
        result = run_with(preds)
        self.assertEqual(failure_count(result), 1)
        self.assertEqual(list(k for k, v in result["failures"].items() if v), ["unit_price"])
        self.assertEqual(result["forms_fully_correct"], len(FORMS) - 1)

    def test_missing_and_extra_items_are_counted(self):
        preds = json.loads(json.dumps(self.perfect))
        items = preds["of-0037"]["contract_items"]
        items[0]["sku_code"] = "COPILOT"  # one wrong SKU = one extra + one missed
        result = run_with(preds)
        self.assertEqual((result["items"]["fp"], result["items"]["fn"]), (1, 1))

    def test_abstention_is_scored_separately(self):
        preds = json.loads(json.dumps(self.perfect))
        header = preds["of-0032"]["order_form"]
        header["effective_date"] = None
        header["ambiguous_fields"] = {"effective_date": {"candidates": ["2024-06-04", "2024-04-06"]}}
        r = run_with(preds)["fields"]["effective_date"]
        self.assertEqual(r["abstained"]["n"], 1)
        self.assertEqual(r["unflagged"]["accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
