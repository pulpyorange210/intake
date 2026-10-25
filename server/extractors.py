"""How an uploaded PDF becomes the parser's output: the live agent (Claude API), or a recorded run replayed
through the current checker (no API key; used for the demo, tests and CI)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

from ofparser import cassette
from ofparser.catalog import Catalog

Extractor = Callable[[Path], dict]


class NoRecording(Exception):
    pass


def live_extractor(catalog: Catalog) -> Extractor:
    import anthropic

    from ofparser.agent import parse_order_form
    client = anthropic.Anthropic()
    return lambda pdf: parse_order_form(pdf, catalog, client)


def replay_extractor(catalog: Catalog, cassettes_dir: Path) -> Extractor:
    """Finds the recording by the PDF's content hash, so a renamed upload of a recorded form still replays."""
    by_hash: Dict[str, Path] = {}
    for path in sorted(Path(cassettes_dir).glob("*.json")):
        by_hash[cassette.load(path)["pdf_sha256"]] = path

    def extract(pdf: Path) -> dict:
        tape = by_hash.get(cassette.pdf_sha256(pdf))
        if tape is None:
            raise NoRecording(f"no recorded run for {Path(pdf).name}; replay mode only knows the forms in "
                              f"{cassettes_dir} (set ANTHROPIC_API_KEY to extract new forms)")
        return cassette.replay(cassette.load(tape), pdf, catalog)

    return extract
