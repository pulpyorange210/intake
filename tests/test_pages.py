"""Page index for long documents: scoring, initial selection, search and read limits."""
import unittest
from pathlib import Path

from ofparser.pages import MAX_FULL_PAGES, MAX_SELECTED, READ_LIMIT, PageIndex
from ofparser.pdf import extract_text
from tests.helpers import DATASET

FILLER = "Each party shall comply with applicable law, subject to Section 4.2.\n" * 30
PRICING = ("Product               Qty      Unit Price        Total\n"
           "Analytics Suite         1      $12,000.00     $36,000.00\n"
           "Premium Support         1       $4,000.00     $12,000.00\n"
           "Invoices are billed annually. Payment terms: Net 30.\n")
SIGNATURES = "By:  ____________   By: ____________\nName (Print): Jane   Title (Print): CFO\nDate Signed: 2024-01-05\n"


def index(pages, names=("Analytics Suite", "Premium Support")):
    return PageIndex.build(Path("unused.pdf"), "\f".join(pages) + "\f", list(names))


class SelectionTest(unittest.TestCase):
    def setUp(self):
        pages = [FILLER] * 100
        pages[56] = PRICING        # page 57
        pages[57] = SIGNATURES     # page 58
        self.idx = index(pages)

    def test_pages_split_on_form_feeds(self):
        self.assertEqual(self.idx.n_pages, 100)

    def test_pricing_page_scores_highest(self):
        best = max(self.idx.scores, key=lambda s: s.score)
        self.assertEqual(best.page, 57)

    def test_selection_has_pricing_neighbours_first_pages_and_signatures(self):
        sel = self.idx.select()
        self.assertTrue({1, 2, 56, 57, 58} <= set(sel))
        self.assertLessEqual(len(sel), MAX_SELECTED)

    def test_signature_page_found_on_its_own(self):
        pages = [FILLER] * 100
        pages[10] = PRICING
        pages[90] = SIGNATURES
        sel = index(pages).select()
        self.assertEqual(sel.get(91), "signature cues")

    def test_plain_boilerplate_is_never_a_top_page(self):
        self.assertEqual(index([FILLER] * 50).select(), {1: "first pages", 2: "first pages"})


class ToolsTest(unittest.TestCase):
    def setUp(self):
        pages = [FILLER] * 40
        pages[19] = PRICING
        self.idx = index(pages)

    def test_search_is_case_and_spacing_insensitive(self):
        result = self.idx.search("net   30")
        self.assertIn("p.20:", result)

    def test_search_falls_back_to_all_words_on_a_line(self):
        self.assertIn("all words on one line", self.idx.search("billed Invoices"))

    def test_search_reports_no_match(self):
        self.assertIn("No matches", self.idx.search("grand total"))

    def test_read_range_is_clamped(self):
        pages, note = self.idx.read_range(35, 60)
        self.assertEqual(pages, list(range(35, 41)))
        pages, note = self.idx.read_range(1, 40)
        self.assertEqual(len(pages), READ_LIMIT)
        self.assertIn("limited", note)


class OutlineTest(unittest.TestCase):
    def setUp(self):
        header = "ACME MASTER AGREEMENT - CONFIDENTIAL\n"
        titles = ["GOVERNING LAW", "NOTICES", "WARRANTIES", "FORCE MAJEURE", "ASSIGNMENT", "PUBLICITY"]
        clause = header + "{n}. {t}\n{n}.1 Each party shall comply with applicable law, as set out in\nExhibit G.\n"
        pages = [clause.format(n=i, t=titles[i % 6]) + f"Page {i} of 60\n" for i in range(1, 61)]
        pages[19] = header + "Order Form\nProduct   Qty   Price\n" + PRICING + "Page 20 of 60\n"
        pages[39] = header + "AMENDMENT NO. 2 TO THE ORDER FORM\nThe price is changed.\n" + "Page 40 of 60\n"
        pages[49] = header + "TERMS\n" + SIGNATURES + "Page 50 of 60\n"
        self.outline = index(pages).outline()
        self.lines = self.outline.splitlines()

    def test_running_headers_and_footers_are_dropped(self):
        self.assertNotIn("ACME MASTER AGREEMENT", self.outline)
        self.assertNotIn("Page 1 of 60", self.outline)

    def test_parts_get_their_own_line_with_hints(self):
        self.assertIn("p.20: Order Form", self.outline)
        self.assertRegex(self.outline, r"p\.20: .*\[score")
        self.assertIn("p.40: AMENDMENT NO. 2 TO THE ORDER FORM", self.outline)
        self.assertRegex(self.outline, r"p\.50: TERMS.*\[signatures\]")

    def test_clause_runs_collapse_and_sentence_tails_are_not_headings(self):
        self.assertIn("p.1-19: 19 numbered clause heading(s), e.g. NOTICES, WARRANTIES", self.outline)
        self.assertNotIn("Exhibit G.", self.outline)
        self.assertLessEqual(len(self.lines), 8)


class ShortDocumentsUnchangedTest(unittest.TestCase):
    def test_every_synthetic_form_is_sent_whole(self):
        for pdf in sorted((DATASET / "pdfs").glob("*.pdf")):
            n = PageIndex.build(pdf, extract_text(pdf), []).n_pages
            self.assertLessEqual(n, MAX_FULL_PAGES, pdf.name)


if __name__ == "__main__":
    unittest.main()
