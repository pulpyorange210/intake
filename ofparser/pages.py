"""Page index for long documents: score every page with plain code, build a compact outline (headings and
page numbers), pick pages to show the model first, and serve search_document / read_pages for the rest.

Scoring uses only generic order-form signals (currency amounts, table-like rows, dates, billing words) and the
catalog's own product names; nothing depends on any particular document's wording.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from pypdf import PdfReader, PdfWriter

from .pdf import dates_in, normalize_for_match

MAX_FULL_PAGES = 30   # documents up to this length are sent whole, as before
TOP_PAGES = 6         # at most this many highest-scoring pages, each sent with its neighbours
RELATIVE_SCORE = 0.35  # other top pages must score at least this fraction of the best page
FIRST_PAGES = 2       # parties, dates and references usually start here
SIGNATURE_PAGES = 3
MAX_SELECTED = 20
READ_LIMIT = 10       # pages per read_pages call
SEARCH_LIMIT = 25     # matching lines returned per search

_AMOUNT = r"\d{1,3}(?:[,.' ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEY = re.compile(rf"[$€£¥₹]\s?(?:{_AMOUNT})|(?:{_AMOUNT})\s?(?:USD|EUR|GBP|INR|JPY|CAD|AUD|CHF)\b"
                    rf"|\b(?:USD|EUR|GBP|INR|JPY|CAD|AUD|CHF)\s?(?:{_AMOUNT})")
_KEYWORDS = re.compile(r"\b(?:qty|quantity|total|subtotal|term|invoices?|invoiced|billing|billed|payment|fees?|"
                       r"price|pricing|start date|end date|order form|subscription)\b", re.I)
_SIGNATURE = re.compile(r"\b(?:signature|signed|signatory|by:|name\s*\(print\)|title\s*\(print\)|title:|"
                        r"date\s*\(print\)|date signed)", re.I)
_CELL_GAP = re.compile(r"\S\s{3,}\S")

# Outline: heading detection on the text layer alone (no font information).
RUNNING_LINE_SHARE = 0.2   # a line (digits ignored) on at least this share of pages is a running header/footer
OUTLINE_HINT_PAGES = 8     # highest-scoring pages tagged in the outline
HEADINGS_PER_PAGE = 4
_NUMBERED = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXL]+\.|[A-Z]\.)\s+(?=\S)")
_LEADER = re.compile(r"(?:\s*\.){4,}\s*")
_PART_WORDS = re.compile(r"^(?:exhibit|schedule|appendix|annex|addendum|amendment|article|part|section)\b", re.I)


@dataclass
class PageScore:
    page: int  # 1-based
    money: int
    table_rows: int
    dates: int
    keywords: int
    catalog_hits: int
    signature_cues: int

    @property
    def score(self) -> float:
        return (3 * min(self.money, 15) + min(self.table_rows, 15) + 0.5 * min(self.dates, 10)
                + 1.5 * min(self.keywords, 10) + 4 * min(self.catalog_hits, 5))


@dataclass
class PageIndex:
    pdf_path: Path
    pages: List[str]                      # text layer per page
    scores: List[PageScore] = field(default_factory=list)

    @classmethod
    def build(cls, pdf_path: Path, full_text: str, catalog_names: Sequence[str]) -> "PageIndex":
        pages = full_text.split("\f")
        if pages and not pages[-1].strip():
            pages = pages[:-1]  # pdftotext ends every page with a form feed
        names = [normalize_for_match(n) for n in catalog_names if n]
        index = cls(Path(pdf_path), pages)
        for i, text in enumerate(pages, start=1):
            norm = normalize_for_match(text)
            index.scores.append(PageScore(
                page=i,
                money=len(_MONEY.findall(text)),
                table_rows=sum(1 for line in text.splitlines()
                               if len(_CELL_GAP.findall(line)) >= 2 and sum(ch.isdigit() for ch in line) >= 2),
                dates=len(dates_in(text)),
                keywords=len(_KEYWORDS.findall(text)),
                catalog_hits=sum(1 for n in names if n in norm),
                signature_cues=len({m.lower() for m in _SIGNATURE.findall(text)}),
            ))
        return index

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    # ---- outline ----
    def _running_lines(self) -> set:
        """Lines repeated on many pages (page headers/footers), compared with digits ignored."""
        if self.n_pages < 10:
            return set()
        counts = Counter()
        for text in self.pages:
            counts.update({re.sub(r"\d+", "#", " ".join(line.split())) for line in text.splitlines() if line.strip()})
        return {line for line, n in counts.items() if n >= RUNNING_LINE_SHARE * self.n_pages}

    @staticmethod
    def _heading_kind(line: str, first_on_page: bool):
        """'part' (document part / page title), 'clause' (numbered clause heading) or None."""
        words = line.split()
        letters = [ch for ch in line if ch.isalpha()]
        if not words or len(words) > 10 or len(letters) < 3 or not any(len(w) >= 4 for w in words):
            return None
        numbered, part_word = bool(_NUMBERED.match(line)), bool(_PART_WORDS.match(line))
        if any(ch.isdigit() for ch in line) and not (numbered or part_word):
            return None  # amounts, dates, table rows
        caps = sum(ch.isupper() for ch in letters) >= 0.8 * len(letters)
        long_words = [w for w in words if len(w) >= 4 and w[0].isalpha()]
        titled = bool(long_words) and sum(w[0].isupper() for w in long_words) >= 0.6 * len(long_words)
        if numbered:
            return "clause" if (caps or titled) else None
        if line[-1] == "." and not caps:
            return None  # a sentence or the tail of one ("... as set out in Exhibit G.")
        if part_word and (caps or titled):
            return "part"
        if caps:
            return "part"
        if first_on_page and titled and len(words) <= 8 and line[-1] not in ".,:;":
            return "part"
        return None

    def outline(self) -> str:
        """Compact outline: each page with document-part headings gets a line; runs of pages that only have
        numbered clause headings (or none) collapse into one line. Score and signature hints are tagged."""
        running = self._running_lines()
        ranked = sorted((s for s in self.scores if s.score > 0), key=lambda s: (-s.score, s.page))
        best = ranked[0].score if ranked else 0
        hints = {s.page: f"score {s.score:g}" for s in ranked[:OUTLINE_HINT_PAGES] if s.score >= RELATIVE_SCORE * best}
        signatures = {s.page for s in self.scores if s.signature_cues >= 2}

        lines: List[str] = []
        run: Dict = {}

        def flush():
            if not run:
                return
            span = f"p.{run['start']}" + (f"-{run['end']}" if run["end"] != run["start"] else "")
            if run["titles"]:
                examples = ", ".join(list(dict.fromkeys(run["titles"]))[:4])
                lines.append(f"{span}: {len(run['titles'])} numbered clause heading(s), e.g. {examples}")
            else:
                lines.append(f"{span}: no headings")
            run.clear()

        for i, text in enumerate(self.pages, start=1):
            parts, clauses, first = [], [], True
            for raw in text.splitlines():
                line = _LEADER.sub(" ... ", " ".join(raw.split())).strip()
                if not line or re.sub(r"\d+", "#", line) in running:
                    continue
                kind = self._heading_kind(line, first)
                first = False
                if kind == "part":
                    parts.append(line[:70])
                elif kind == "clause":
                    clauses.append(_NUMBERED.sub("", line).strip()[:40] or line[:40])
            tags = [t for t in (hints.get(i), "signatures" if i in signatures else None) if t]
            if parts or tags:
                flush()
                shown = " | ".join(parts[:HEADINGS_PER_PAGE]) or "(no part heading)"
                more = f" (+{len(parts) - HEADINGS_PER_PAGE} more)" if len(parts) > HEADINGS_PER_PAGE else ""
                extra = f"; {len(clauses)} numbered clause heading(s)" if clauses else ""
                lines.append(f"p.{i}: {shown}{more}{extra}" + (f" [{', '.join(tags)}]" if tags else ""))
            else:
                if not run:
                    run.update(start=i, titles=[])
                run["end"] = i
                run["titles"] += clauses
        flush()
        return "\n".join(lines)

    # ---- initial selection ----
    def select(self) -> Dict[int, str]:
        """Pages to send first, mapped to why each was picked, in priority order, capped at MAX_SELECTED."""
        chosen: Dict[int, str] = {}

        def add(page: int, why: str) -> None:
            if 1 <= page <= self.n_pages and page not in chosen and len(chosen) < MAX_SELECTED:
                chosen[page] = why

        ranked = sorted((s for s in self.scores if s.score > 0), key=lambda s: (-s.score, s.page))
        if ranked:
            best = ranked[0].score
            ranked = [s for s in ranked[:TOP_PAGES] if s.score >= RELATIVE_SCORE * best]
        for s in ranked:
            add(s.page, f"top score {s.score:g}")
        for p in range(1, FIRST_PAGES + 1):
            add(p, "first pages")
        for s in ranked:
            add(s.page - 1, f"before page {s.page}")
            add(s.page + 1, f"after page {s.page}")
        signed = sorted((s for s in self.scores if s.signature_cues >= 2),
                        key=lambda s: (-s.signature_cues, -s.score, s.page))
        for s in signed[:SIGNATURE_PAGES]:
            add(s.page, "signature cues")
        return dict(sorted(chosen.items()))

    # ---- what the model sees ----
    def labelled_text(self, pages: Sequence[int]) -> str:
        return "\n".join(f"=== Page {p} of {self.n_pages} ===\n{self.pages[p - 1]}" for p in pages)

    def pdf_of(self, pages: Sequence[int]) -> bytes:
        reader = PdfReader(str(self.pdf_path))
        writer = PdfWriter()
        for p in pages:
            writer.add_page(reader.pages[p - 1])
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    # ---- tools ----
    def search(self, query: str) -> str:
        """Lines containing the query (case- and spacing-insensitive); if none, lines containing all its words."""
        q = normalize_for_match(query)
        words = [normalize_for_match(w) for w in query.split() if w.strip()]
        if not q:
            return "Empty query."

        def scan(match) -> List[Tuple[int, str]]:
            return [(i, line.strip()) for i, text in enumerate(self.pages, start=1)
                    for line in text.splitlines() if line.strip() and match(normalize_for_match(line))]

        hits = scan(lambda line: q in line)
        how = "exact"
        if not hits and len(words) > 1:
            hits = scan(lambda line: all(w in line for w in words))
            how = "all words on one line"
        if not hits:
            return f"No matches for {query!r} in the {self.n_pages}-page document."
        pages = sorted({p for p, _ in hits})
        lines = [f"{len(hits)} matching line(s) ({how}) on {len(pages)} page(s): "
                 f"{', '.join(map(str, pages[:60]))}{' ...' if len(pages) > 60 else ''}"]
        lines += [f"p.{p}: {re.sub(r'  +', '  ', line)[:200]}" for p, line in hits[:SEARCH_LIMIT]]
        if len(hits) > SEARCH_LIMIT:
            lines.append(f"... {len(hits) - SEARCH_LIMIT} more; narrow the query or read the pages listed above.")
        return "\n".join(lines)

    def read_range(self, first: int, last: int) -> Tuple[List[int], str]:
        """Clamp a requested range to the document and READ_LIMIT; returns (pages, note about any clamping)."""
        first, last = max(1, int(first)), min(self.n_pages, int(last))
        if last < first:
            return [], f"No pages in that range; the document has pages 1-{self.n_pages}."
        note = ""
        if last - first + 1 > READ_LIMIT:
            last = first + READ_LIMIT - 1
            note = f" (limited to {READ_LIMIT} pages per call; request {last + 1} onwards separately)"
        return list(range(first, last + 1)), note
