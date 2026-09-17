"""Capabilities supported by a loaded inspection workbook."""

from __future__ import annotations

from enum import StrEnum

from .model import Workbook


class Capability(StrEnum):
    CACHED_VALUES = "CACHED_VALUES"
    FORMULA_TOKENS = "FORMULA_TOKENS"
    NUMBER_FORMATS = "NUMBER_FORMATS"
    REF_GRAPH = "REF_GRAPH"


def capabilities(workbook: Workbook) -> frozenset[Capability]:
    """Report capabilities conservatively; absent formula caches are explicit."""
    formula_cells = tuple(
        cell for sheet in workbook.sheets for cell in sheet.cells if cell.formula is not None
    )
    available = {
        Capability.FORMULA_TOKENS,
        Capability.NUMBER_FORMATS,
        Capability.REF_GRAPH,
    }
    if all(cell.cached_value is not None for cell in formula_cells):
        available.add(Capability.CACHED_VALUES)
    return frozenset(available)
