"""PDF loading, text-layer extraction, and helpers for grounding values in the document."""
from __future__ import annotations

import base64
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


# Numbers with thousands separators (1,234.56) or plain (1234.56 / 30).
_NUMBER = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\d.,])\d+(?:\.\d+)?")


def to_decimal(value) -> Decimal:
    return Decimal(str(value))


def cents(value) -> Decimal:
    return to_decimal(value).quantize(Decimal("0.01"))


def numbers_in(text: str) -> Set[Decimal]:
    """Every number printed in the document, normalized to cents for comparison."""
    found = set()
    for match in _NUMBER.findall(text):
        try:
            found.add(cents(match.replace(",", "")))
        except InvalidOperation:
            continue
    return found


def normalize_for_match(text: str) -> str:
    """Lowercase and drop all whitespace so quotes match regardless of layout spacing."""
    return re.sub(r"\s+", "", text).lower()
