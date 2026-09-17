"""Ratchet: domain nouns stay out of the inspection and lint packages."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "xllib"

# From GOAL.md: Layers 0-2 must not know these consulting-domain nouns.
_NOUNS = (
    r"value[_\s-]?case",
    r"benefit(?:s|_line|_owner)?",
    r"baseline",
    r"\bfte\b",
)

_PATTERN = re.compile("|".join(_NOUNS), re.IGNORECASE)
_SKIP = {".pyc"}


def test_core_packages_contain_no_domain_nouns() -> None:
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        if path.suffix in _SKIP:
            continue
        text = path.read_text(encoding="utf-8")
        for match in _PATTERN.finditer(text):
            rel = path.relative_to(ROOT)
            line = text[: match.start()].count("\n") + 1
            hits.append(f"{rel}:{line}:{match.group(0)}")
    assert hits == []
