"""Generate long-document test PDFs: contract boilerplate with decoy pages, and the real example
order form inserted unchanged at a chosen page.

Seeded and reproducible: the same seed and variant give the same PDF bytes.

Most variants insert the form's 5 pages together. The scattered variant spreads the form apart: its first page
(term, pricing, invoicing schedule) is split into three pages placed far apart, its signature page goes
elsewhere, and a one-page amendment that changes a price comes near the end. Cropping a copy of the original
page is not enough to split it (a live check showed the model still reads text outside the crop), so each
split piece is redrawn as a new page from the original page's words, at their original positions and sizes.

  python scripts/make_long_doc.py            # all variants -> edge_cases/long_document/generated/
  python scripts/make_long_doc.py --only n1000_at412

Decoys are pages that look relevant to a page scorer but are not the order form:
- a table of contents that points to the order form's page,
- an optional-services rate card (priced, using catalog-like product names, explicitly not purchased),
- SLA tables full of numbers and percentages,
- amendment / notice logs dense with dates and section numbers,
- occasional dollar amounts inside ordinary clauses (liability caps, insurance minimums).
"""
from __future__ import annotations

import argparse
import html
import io
import json
import random
import re
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
FORM_PDF = ROOT / "edge_cases" / "example_order_form_redacted" / "input.pdf"
OUT_DIR = ROOT / "edge_cases" / "long_document" / "generated"

# name -> (total pages, first page of the inserted order form)
VARIANTS = {
    "n1000_at412": (1000, 412),  # main case: form in the middle
    "n1000_at3": (1000, 3),      # form near the start
    "n1000_at990": (1000, 990),  # form near the end
    "n200_at82": (200, 82),
    "n500_at206": (500, 206),
}

# The form's first page split into bands (top / bottom, in points from the top of the page).
BANDS = {"term": (95, 275), "pricing": (280, 405), "invoicing": (445, 720)}

# Scattered variant: page -> what goes there. ("band", name) = a redrawn piece of the form's first page,
# ("orig", i) = original form page i (0-based), ("amendment",) = the generated amendment page.
SCATTERED = {
    "n1000_scattered": (1000, {
        120: ("band", "term"),
        415: ("band", "pricing"),
        416: ("orig", 2), 417: ("orig", 3), 418: ("orig", 4),  # product descriptions, not needed
        640: ("band", "invoicing"),
        880: ("orig", 1),                                      # terms and signatures
        955: ("amendment",),
    }),
}
SCATTERED_NEEDED = {120: "service term (start and end dates)", 415: "pricing table",
                    640: "invoicing schedule and payment terms", 880: "signatures", 955: "amendment changing a price"}

WIDTH, HEIGHT = letter
MARGIN = 54
LINE = 12

SUBJECTS = ["Provider", "Customer", "Either party", "Each party", "The receiving party", "The disclosing party",
            "Neither party", "The Licensor", "The Licensee", "Any Affiliate"]
VERBS = ["shall", "may", "shall not", "agrees to", "will use commercially reasonable efforts to",
         "acknowledges that it will"]
ACTIONS = ["maintain the confidentiality of all Confidential Information", "comply with applicable data protection laws",
           "provide written notice of any material breach", "indemnify and hold harmless the other party",
           "retain records for the duration required by law", "cooperate in good faith to resolve any dispute",
           "implement appropriate technical and organisational measures", "assign its rights only with prior consent",
           "remedy any non-conformity within a reasonable period", "make the Documentation available to Users",
           "not reverse engineer or decompile any component of the Services",
           "restrict access to authorised personnel with a need to know"]
QUALIFIERS = ["subject to Section {s}", "except as expressly provided in Section {s}",
              "in accordance with the Documentation", "during the Term and for a period thereafter",
              "to the extent permitted by applicable law", "notwithstanding anything to the contrary herein",
              "as further described in Exhibit {x}", "unless otherwise agreed in writing by the parties"]
TITLES = ["Definitions", "Grant of Rights", "Restrictions", "Confidentiality", "Data Protection", "Security",
          "Intellectual Property", "Warranties", "Disclaimers", "Indemnification", "Limitation of Liability",
          "Term and Termination", "Effect of Termination", "Governing Law", "Dispute Resolution", "Force Majeure",
          "Assignment", "Notices", "Audit Rights", "Insurance", "Subcontractors", "Export Control", "Publicity",
          "Non-Solicitation", "Anti-Corruption", "Accessibility", "Business Continuity", "Records Retention"]


class Doc:
    def __init__(self, total_pages: int, reserved: set, seed: int):
        """reserved: final page numbers that inserted pages will occupy; generated pages skip them."""
        self.rng = random.Random(seed)
        self.total = total_pages
        self.reserved = set(reserved)
        self.form_at = min(self.reserved)
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=letter, invariant=1)  # invariant: no timestamps, stable bytes
        self.section = [1, 1]
        self.page_no = 0  # final page number of the page being drawn

    # ---- page plumbing ----
    def next_page_no(self) -> int:
        n = self.page_no + 1
        while n in self.reserved:  # skip the numbers inserted pages will occupy
            n += 1
        return n

    def page(self, lines):
        self.page_no = self.next_page_no()
        c = self.c
        c.setFont("Helvetica", 7)
        c.drawString(MARGIN, HEIGHT - 36, "MASTER SERVICES AGREEMENT - CONFIDENTIAL")
        c.drawRightString(WIDTH - MARGIN, 30, f"Page {self.page_no} of {self.total}")
        y = HEIGHT - MARGIN - 10
        for item in lines:
            if isinstance(item, tuple):  # (font size, bold, text) or a table row of (x, text) cells
                if item and isinstance(item[0], list):
                    c.setFont("Helvetica", 9)
                    for x, text in item[0]:
                        c.drawString(MARGIN + x, y, text)
                else:
                    size, bold, text = item
                    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
                    c.drawString(MARGIN, y, text)
            else:
                c.setFont("Helvetica", 9)
                c.drawString(MARGIN, y, item)
            y -= LINE
            if y < MARGIN:
                break
        c.showPage()

    # ---- content ----
    def wrap(self, text: str, width: int = 105):
        words, line, out = text.split(), "", []
        for w in words:
            if len(line) + len(w) + 1 > width:
                out.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        if line:
            out.append(line)
        return out

    def sentence(self) -> str:
        r = self.rng
        s = f"{r.choice(SUBJECTS)} {r.choice(VERBS)} {r.choice(ACTIONS)}, {r.choice(QUALIFIERS)}."
        s = s.format(s=f"{r.randint(1, 40)}.{r.randint(1, 9)}", x=r.choice("ABCDEFGH"))
        if r.random() < 0.06:  # money inside ordinary clauses
            s += r.choice([f" Liability under this Section is capped at ${r.choice([1, 2, 5])},000,000.00.",
                           f" Provider shall maintain insurance of not less than ${r.choice([2, 5, 10])},000,000.",
                           f" Late payments accrue interest at {r.choice(['1.0', '1.5'])}% per month."])
        return s

    def boilerplate_page(self):
        r = self.rng
        lines = []
        while len(lines) < 52:
            if r.random() < 0.25:
                self.section[0] += 1
                self.section[1] = 1
                lines += ["", (11, True, f"{self.section[0]}. {r.choice(TITLES).upper()}")]
            para = " ".join(self.sentence() for _ in range(r.randint(2, 4)))
            lines += self.wrap(f"{self.section[0]}.{self.section[1]} {para}") + [""]
            self.section[1] += 1
        self.page(lines)

    def toc_page(self):
        r = self.rng
        lines = [(13, True, "TABLE OF CONTENTS"), ""]
        entries = [(f"{i + 1}. {t}", r.randint(5, self.total - 5)) for i, t in enumerate(r.sample(TITLES, 22))]
        entries.append(("Exhibit C - Sales Order Form", self.form_at))
        entries.append(("Exhibit D - Schedule of Optional Services and Rates", r.randint(20, self.total - 20)))
        entries.append(("Exhibit E - Service Level Agreement", r.randint(20, self.total - 20)))
        entries.sort(key=lambda e: e[1])
        for title, pg in entries:
            lines.append(((([(0, title), (360, "." * 30), (470, str(pg))]),)))
        self.page(lines)

    def rate_card_page(self):
        r = self.rng
        rows = [("Professional Services - Implementation", "per hour", f"${r.choice([250, 275, 300])}.00"),
                ("Professional Services - Training Workshop", "per day", f"${r.choice([3200, 3600])}.00"),
                ("Data Analytics Add-on", "per year", f"${r.choice([42, 48, 54])},000.00"),
                ("Premium Support - Enhanced Tier", "per year", f"${r.choice([58, 62, 66])},500.00"),
                ("Sandbox Environment", "per year", f"${r.choice([15, 18])},000.00"),
                ("Additional Data Storage (1 TB)", "per month", f"${r.choice([400, 450])}.00"),
                ("Dedicated Customer Success Manager", "per year", f"${r.choice([95, 110])},000.00")]
        lines = [(13, True, "EXHIBIT D - SCHEDULE OF OPTIONAL SERVICES AND RATES"), ""]
        lines += self.wrap("The following optional services are available on request at the rates below. They are not "
                           "included in, and are not purchased under, any Order Form unless separately ordered in "
                           "writing. Rates are list prices in USD and exclude applicable taxes.")
        lines += ["", ([(0, "Service"), (260, "Unit"), (360, "Qty"), (420, "Rate (USD)")],)]
        for name, unit, rate in rows:
            lines.append(([(0, name), (260, unit), (360, "1"), (420, rate)],))
        lines += [""] + self.wrap("Rates may be adjusted annually upon sixty (60) days written notice. Minimum "
                                  "engagement for Professional Services is eight (8) hours.")
        self.page(lines)

    def sla_page(self):
        r = self.rng
        lines = [(13, True, "EXHIBIT E - SERVICE LEVEL AGREEMENT"), "",
                 ([(0, "Service Level"), (200, "Target"), (290, "Measurement"), (400, "Service Credit")],)]
        for name in ["Monthly Uptime", "API Availability", "P1 Response Time", "P2 Response Time",
                     "P3 Response Time", "Data Restore (RPO)", "Recovery Time (RTO)", "Support Hours Coverage"]:
            target = r.choice(["99.9%", "99.95%", "99.5%", "1 hour", "4 hours", "8 hours", "24 hours"])
            credit = f"{r.choice([5, 10, 15, 25])}% of monthly fees"
            lines.append(([(0, name), (200, target), (290, r.choice(["monthly", "per incident", "quarterly"])),
                           (400, credit)],))
        lines += [""] + self.wrap("Service credits are the sole and exclusive remedy for failure to meet the targets "
                                  "above and shall not exceed 30% of the fees for the affected month.")
        self.page(lines)

    def date_log_page(self):
        r = self.rng
        lines = [(13, True, "AMENDMENT AND NOTICE LOG"), "",
                 ([(0, "Ref"), (60, "Section"), (140, "Effective"), (240, "Notice Given"), (340, "Description")],)]
        for i in range(30):
            def d():
                return f"{r.randint(1, 12):02d}/{r.randint(1, 28):02d}/{r.randint(2015, 2026)}"
            lines.append(([(0, f"A-{r.randint(1, 99):02d}"), (60, f"{r.randint(1, 40)}.{r.randint(1, 9)}.{r.randint(1, 9)}"),
                           (140, d()), (240, d()), (340, r.choice(["Notice address updated", "Clause restated",
                                                                    "Cure period extended", "Definition amended",
                                                                    "Exhibit replaced"]))],))
        self.page(lines)

    def build(self) -> bytes:
        r = self.rng
        n_generated = self.total - len(self.reserved)
        specials = {2: self.toc_page}
        for kind, count in ((self.rate_card_page, 2), (self.sla_page, 3), (self.date_log_page, 4)):
            for _ in range(count):
                slot = r.randint(4, n_generated - 1)
                while slot in specials:
                    slot = r.randint(4, n_generated - 1)
                specials[slot] = kind
        for i in range(1, n_generated + 1):
            specials.get(i, self.boilerplate_page)()
        self.c.save()
        return self.buf.getvalue()


def form_words(page: int = 1):
    """Words on a page of the original form with their boxes (points from the top), via pdftotext -bbox."""
    xml = subprocess.run(["pdftotext", "-bbox", "-f", str(page), "-l", str(page), str(FORM_PDF), "-"],
                         capture_output=True, text=True, check=True).stdout
    pattern = r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>'
    return [(float(a), float(b), float(c), float(d), html.unescape(t)) for a, b, c, d, t in re.findall(pattern, xml)]


def band_page(name: str) -> bytes:
    """One band of the form's first page, redrawn on a new letter page: same words, positions and sizes."""
    top, bottom = BANDS[name]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    shift = top - 72  # move the band to the top of the new page
    for x0, y0, x1, y1, text in form_words():
        if top <= y0 and y1 <= bottom:
            size = max(6.0, (y1 - y0) * 0.8)
            c.setFont("Helvetica", size)
            c.drawString(x0, HEIGHT - (y1 - shift) + (y1 - y0) * 0.22, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def amendment_page() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    y = HEIGHT - 80
    c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN, y, "AMENDMENT NO. 1 TO SALES ORDER FORM")
    y -= 26
    paras = [
        'This Amendment No. 1 ("Amendment") is entered into as of 10/27/2023 between AI Inc. and Customer, and amends '
        'the Sales Order Form for the Subscription Services with a Start Date of 11/1/2023 (the "Order Form").',
        "1. Premium Support fee. The annual fee for Premium Support set out in the Subscription Service Fees table of "
        "the Order Form is replaced with $45,000.00 per year for each of Year 1, Year 2 and Year 3.",
        "2. Totals. Accordingly, the Total Subscription per year is $375,000.00 and the Total Amount Due under the "
        "Order Form is $1,125,000.00.",
        "3. Invoicing. Each annual invoice under the Invoicing Schedule of the Order Form is amended to $375,000.00.",
        "4. All other terms of the Order Form remain unchanged and in full force and effect.",
    ]
    c.setFont("Helvetica", 10)
    for para in paras:
        words, line = para.split(), ""
        for w in words:
            if c.stringWidth(f"{line} {w}", "Helvetica", 10) > WIDTH - 2 * MARGIN:
                c.drawString(MARGIN, y, line)
                y -= 14
                line = w
            else:
                line = f"{line} {w}".strip()
        c.drawString(MARGIN, y, line)
        y -= 24
    y -= 10
    for x, lines in ((MARGIN, ["AI Inc.", "By: ____________________", "Date: 10/27/2023"]),
                     (WIDTH / 2, ["Customer", "By: ____________________", "Date: 10/30/2023"])):
        for i, text in enumerate(lines):
            c.drawString(x, y - 16 * i, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def assemble(name: str, total: int, inserts: dict, seed: int) -> Path:
    """inserts: final page number -> pypdf page object."""
    generated = list(PdfReader(io.BytesIO(Doc(total, set(inserts), seed).build())).pages)
    writer = PdfWriter()
    gen = iter(generated)
    for n in range(1, total + 1):
        writer.add_page(inserts[n] if n in inserts else next(gen))
    assert len(writer.pages) == total, (name, len(writer.pages))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.pdf"
    with open(out, "wb") as f:
        writer.write(f)
    return out


def make_variant(name: str, total: int, form_at: int, seed: int = 7) -> Path:
    form = PdfReader(str(FORM_PDF))  # the original pages, unchanged
    return assemble(name, total, {form_at + i: p for i, p in enumerate(form.pages)}, seed)


def make_scattered(name: str, seed: int = 7) -> Path:
    total, layout = SCATTERED[name]
    form = PdfReader(str(FORM_PDF))
    inserts = {}
    for page_no, spec in layout.items():
        if spec[0] == "orig":
            inserts[page_no] = form.pages[spec[1]]
        elif spec[0] == "band":
            inserts[page_no] = PdfReader(io.BytesIO(band_page(spec[1]))).pages[0]
        else:
            inserts[page_no] = PdfReader(io.BytesIO(amendment_page())).pages[0]
    return assemble(name, total, inserts, seed)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="variant names to build (default: all)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    names = args.only or list(VARIANTS) + list(SCATTERED)
    for name in names:
        if name in SCATTERED:
            out = make_scattered(name, args.seed)
            print(f"{out.relative_to(ROOT)}: {SCATTERED[name][0]} pages, form pieces at {sorted(SCATTERED[name][1])}")
            continue
        total, form_at = VARIANTS[name]
        out = make_variant(name, total, form_at, args.seed)
        print(f"{out.relative_to(ROOT)}: {total} pages, order form at pages {form_at}-{form_at + 4}")
    info = {n: {"pages": t, "form_first_page": a, "expected": "expected.json",
                "needed_pages": {str(a): "pricing, service term, invoicing schedule and payment terms",
                                 str(a + 1): "signatures"}}
            for n, (t, a) in VARIANTS.items()}
    for n, (t, layout) in SCATTERED.items():
        info[n] = {"pages": t, "form_first_page": min(layout), "expected": "expected_scattered.json",
                   "needed_pages": {str(k): v for k, v in SCATTERED_NEEDED.items()}}
    (OUT_DIR.parent / "variants.json").write_text(json.dumps(info, indent=2) + "\n")


if __name__ == "__main__":
    main()
