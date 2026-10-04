"""SKU catalog loading, prompt formatting, and fuzzy search for large catalogs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

INLINE_LIMIT = 200   # catalogs up to this size go into the prompt; larger ones are searched
TOP_K = 5
SIBLINGS_PER_MATCH = 3
SIBLING_SIMILARITY = 0.5

# OCR-confusable characters are treated as equal: 0/o, 1/l/i/|, 5/s, 8/b.
_CONFUSABLE = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l", "5": "s", "8": "b"})
_STOP = {"the", "of", "for", "and", "to", "a", "an", "usd", "eur", "gbp", "inr", "cad", "aud", "chf", "jpy"}


def _tokens(text: str) -> List[str]:
    """Lowercased word tokens with OCR confusables folded; numbers, amounts and filler words dropped."""
    text = re.sub(r"add[\s-]*on", "addon", text.lower())
    out = []
    for tok in re.findall(r"[a-z0-9|]+", text):
        if not re.search(r"[a-z]", tok) or tok in _STOP:
            continue  # amounts, quantities, currency codes
        out.append(tok.translate(_CONFUSABLE))
    return out


def _within_one_edit(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = j = edits = 0
    while i < len(a) and j < len(b):
        if a[i] != b[j]:
            edits += 1
            if edits > 1:
                return False
            if len(a) == len(b):
                i += 1
        else:
            i += 1
        j += 1
    return edits + (len(b) - j) + (len(a) - i) <= 1


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _token_match(q: str, e: str) -> float:
    """How well a document token matches a catalog token: exact, abbreviation, or typo."""
    if q == e:
        return 1.0
    if len(q) >= 3 and e.startswith(q):
        return 0.9                       # "platf" -> "platform", "prem" -> "premium"
    if len(q) == 2 and e.startswith(q):
        return 0.6                       # "ed" -> "edition": weak on its own
    if len(q) >= 3 and q[0] == e[0] and len(q) < len(e) and _is_subsequence(q, e):
        return 0.8                       # "mgmt" -> "management"
    if len(q) >= 4 and _within_one_edit(q, e):
        return 0.8                       # one-character typo
    return 0.0


class Catalog:
    def __init__(self, entries: List[dict]):
        self.entries = entries
        self.by_code: Dict[str, dict] = {e["sku_code"]: e for e in entries}

        self._name_tokens = {e["sku_code"]: _tokens(e["name"]) for e in entries}

    @property
    def inline(self) -> bool:
        return len(self.entries) <= INLINE_LIMIT

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        return cls(json.loads(Path(path).read_text()))

    def to_prompt(self) -> str:
        blocks = []
        for e in self.entries:
            blocks.append(
                f"- code: {e['sku_code']}\n"
                f"  name: {e['name']}\n"
                f"  description: {e.get('description') or ''}\n"
                f"  parsing_instructions: |\n"
                + "\n".join(f"    {line}" for line in (e.get("parsing_instructions") or "").splitlines())
            )
        return "\n".join(blocks)

    # ---- search (large catalogs) ----
    def _score(self, query: List[str], name: List[str]) -> float:
        """Dice-style overlap: matched weight over the size of both token lists, so unmatched words on
        either side (a region, an edition the document doesn't mention) lower the score."""
        if not query or not name:
            return 0.0
        used, matched = set(), 0.0
        for q in query:
            best, best_j = 0.0, None
            for j, e in enumerate(name):
                if j not in used:
                    m = _token_match(q, e)
                    if m > best:
                        best, best_j = m, j
            if best_j is not None:
                used.add(best_j)
                matched += best
        return 2 * matched / (len(query) + len(name))

    def search(self, line_text: str) -> List[Tuple[dict, float, str]]:
        """Top matches for a line of document text plus close siblings of each: (entry, score, why)."""
        query = _tokens(line_text)
        scored = sorted(((self._score(query, toks), code) for code, toks in self._name_tokens.items()),
                        key=lambda x: (-x[0], len(self._name_tokens[x[1]]), x[1]))
        top = [(code, sc) for sc, code in scored[:TOP_K] if sc > 0]
        results, seen = [], set()
        for code, sc in top:
            results.append((self.by_code[code], sc, "match"))
            seen.add(code)
        for code, _ in top:
            mine = set(self._name_tokens[code])
            sibs = sorted(((len(mine & set(t)) / len(mine | set(t)), c) for c, t in self._name_tokens.items()
                           if c not in seen and mine and t), reverse=True)
            for sim, c in sibs[:SIBLINGS_PER_MATCH]:
                if sim >= SIBLING_SIMILARITY:
                    results.append((self.by_code[c], self._score(query, self._name_tokens[c]), f"sibling of {code}"))
                    seen.add(c)
        return results

    def search_text(self, line_text: str) -> Tuple[str, List[str]]:
        """search() formatted for the model, plus the candidate codes returned."""
        results = self.search(line_text)
        if not results:
            return f"No catalog entries resemble {line_text!r}.", []
        lines = [f"Catalog candidates for {line_text!r} (best first; siblings are similar SKUs to rule out):"]
        for e, sc, why in results:
            instr = " ".join((e.get("parsing_instructions") or "").split())
            lines.append(f"- {e['sku_code']} | {e['name']} | {e.get('description') or ''}"
                         + (f" | instructions: {instr[:240]}" if instr else "") + f"  [{why}, score {sc:.2f}]")
        return "\n".join(lines), [e["sku_code"] for e, _, _ in results]
