"""Catalog search for large catalogs: abbreviations, OCR errors, siblings, and the inline/retrieval switch."""
import unittest

from ofparser.catalog import INLINE_LIMIT, Catalog


def entry(code, name):
    return {"sku_code": code, "name": name, "description": "", "parsing_instructions": ""}


CATALOG = Catalog([
    entry("TM_ENT", "Talent Management Enterprise"),
    entry("TM_ENT_EMEA", "Talent Management Enterprise - EMEA"),
    entry("TM_ENT_PLUS", "Talent Management Enterprise Plus"),
    entry("TM_ESS", "Talent Management Essentials"),
    entry("PREM_SUP", "Premium Support"),
    entry("PREM_SUP_ADDON", "Premium Support (Add-on)"),
    entry("TIP_ADDON", "Talent Intelligence Platform Premium Edition (Add-on)"),
    entry("TIP", "Talent Intelligence Platform"),
    entry("SANDBOX", "Sandbox"),
])


def first(text):
    return CATALOG.search(text)[0][0]["sku_code"]


class SearchTest(unittest.TestCase):
    def test_abbreviations(self):
        self.assertEqual(first("Talent Mgmt Ent. 1 $33,200.98 $796,823.52"), "TM_ENT")
        self.assertEqual(first("Talent Intel. Platf. Prem. Ed. (Add-on)"), "TIP_ADDON")

    def test_ocr_errors(self):
        self.assertEqual(first("Prem. 5upport 2 $213,579.42"), "PREM_SUP")
        self.assertEqual(first("Talent lntel. Platf. 3 97,858.24 USD"), "TIP")

    def test_unmentioned_region_or_edition_ranks_below_the_base_product(self):
        codes = [e["sku_code"] for e, _, _ in CATALOG.search("Talent Management Enterprise")]
        self.assertEqual(codes[0], "TM_ENT")
        self.assertLess(codes.index("TM_ENT"), codes.index("TM_ENT_EMEA"))

    def test_add_on_is_matched_when_printed(self):
        self.assertEqual(first("Premium Support (Add-on)"), "PREM_SUP_ADDON")
        self.assertEqual(first("Premium Support"), "PREM_SUP")

    def test_siblings_are_returned_and_labelled(self):
        results = CATALOG.search("Sandbox")
        self.assertEqual(results[0][0]["sku_code"], "SANDBOX")
        why = {e["sku_code"]: w for e, _, w in CATALOG.search("Talent Mgmt Ent.")}
        self.assertIn("TM_ENT_PLUS", why)

    def test_unrelated_text_returns_nothing(self):
        self.assertEqual(CATALOG.search("Limitation of liability 12.3"), [])

    def test_formatted_result_lists_codes(self):
        text, codes = CATALOG.search_text("Talent Mgmt Ent.")
        self.assertIn("TM_ENT | Talent Management Enterprise", text)
        self.assertEqual(codes[0], "TM_ENT")


class ModeTest(unittest.TestCase):
    def test_small_catalogs_stay_inline(self):
        self.assertTrue(CATALOG.inline)
        big = Catalog([entry(f"SKU_{i}", f"Product {i}") for i in range(INLINE_LIMIT + 1)])
        self.assertFalse(big.inline)


if __name__ == "__main__":
    unittest.main()
