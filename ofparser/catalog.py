"""SKU catalog loading and prompt formatting."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


class Catalog:
    def __init__(self, entries: List[dict]):
        self.entries = entries
        self.by_code: Dict[str, dict] = {e["sku_code"]: e for e in entries}

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
