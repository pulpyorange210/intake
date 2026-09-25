"""PDF loading, text-layer extraction, and helpers for grounding values in the document."""
from __future__ import annotations

import base64
import calendar
import datetime as dt
import re
import shutil
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Set


def extract_text(pdf_path: Path) -> str:
    """Text layer via poppler's pdftotext; -layout keeps table columns aligned."""
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not found - install poppler (e.g. `brew install poppler`)")
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def pdf_base64(pdf_path: Path) -> str:
    return base64.standard_b64encode(Path(pdf_path).read_bytes()).decode("ascii")


# Number notations, each paired with how to normalize it to a plain decimal string:
#   1,234.56 / 1234.56 / 30          (comma thousands, dot decimal)
#   1.234,56 / 1234,56               (dot thousands, comma decimal)
#   1 234,56 / 1'234.56 / 1 234.56   (space, no-break space or apostrophe thousands)
_NOTATIONS = [
    (re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])|(?<![\d.,])\d+(?:\.\d+)?(?![\d,])"),
     lambda s: s.replace(",", "")),
    (re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d.])|(?<![\d.,])\d+,\d+(?![\d.])"),
     lambda s: s.replace(".", "").replace(",", ".")),
    (re.compile(r"(?<![\d.,])\d{1,3}(?:[   ']\d{3})+(?:[.,]\d+)?"),
     lambda s: re.sub(r"[   ']", "", s).replace(",", ".")),
]
MIN_TEXT_LAYER_CHARS = 100


def to_decimal(value) -> Decimal:
    return Decimal(str(value))


def cents(value) -> Decimal:
    return to_decimal(value).quantize(Decimal("0.01"))


def numbers_in(text: str) -> Set[Decimal]:
    """Every number printed in the document, normalized to cents for comparison.

    Each token is read under every notation it fits (e.g. "1,234" as 1234 and as 1.234), since the
    document's locale isn't known; this only widens the set of values an amount may be grounded in.
    """
    found = set()
    for pattern, normalize in _NOTATIONS:
        for match in pattern.findall(text):
            try:
                found.add(cents(normalize(match)))
            except InvalidOperation:
                continue
    return found


_MONTH = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
          r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?![a-z])\.?")
_SEP = r"[\s\-.,/]*"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_YMD = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_NUMERIC = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})(?!\d)")
_DAY_MONTH = re.compile(rf"(?<!\d){_DAY}{_SEP}(?:of\s+)?{_MONTH}{_SEP}(\d{{4}})(?!\d)", re.I)
_MONTH_DAY = re.compile(rf"(?<![a-z]){_MONTH}{_SEP}{_DAY}{_SEP}(\d{{4}})(?!\d)", re.I)


def _month_number(name: str) -> int:
    return [m.lower() for m in calendar.month_abbr].index(name[:3].lower())


def dates_in(text: str) -> Set[dt.date]:
    """Every date printed in the document, in any common format.

    A numeric date whose day and month could be swapped (06/04/2024) is read both ways: this only
    decides whether a date is present at all; choosing between readings is the ambiguity rule's job.
    """
    found: Set[dt.date] = set()

    def add(year, month, day):
        year = int(year)
        year = year + 2000 if year < 100 else year
        try:
            found.add(dt.date(year, int(month), int(day)))
        except ValueError:
            pass

    for y, m, d in _YMD.findall(text):
        add(y, m, d)
    for a, b, y in _NUMERIC.findall(text):
        add(y, a, b)
        add(y, b, a)
    for d, m, y in _DAY_MONTH.findall(text):
        add(y, _month_number(m), d)
    for m, d, y in _MONTH_DAY.findall(text):
        add(y, _month_number(m), d)
    return found


def add_months(date: dt.date, months: int) -> dt.date:
    """Calendar month arithmetic, clamped to the end of shorter months (Jan 31 + 1 month = Feb 28/29)."""
    year, month = divmod(date.month - 1 + months, 12)
    year += date.year
    return dt.date(year, month + 1, min(date.day, calendar.monthrange(year, month + 1)[1]))


def has_text_layer(text: str) -> bool:
    """Scanned PDFs have (almost) no extractable text; grounding against it would reject everything."""
    return len(re.sub(r"\s+", "", text)) >= MIN_TEXT_LAYER_CHARS


def normalize_for_match(text: str) -> str:
    """Lowercase and drop all whitespace so quotes match regardless of layout spacing."""
    return re.sub(r"\s+", "", text).lower()
