"""Formula reference graph construction."""

from __future__ import annotations

from dataclasses import dataclass

from openpyxl.utils.cell import range_boundaries

from .model import Cell, Reference, Workbook
from .tokens import walk_formula

_AGGREGATE_FUNCTIONS = frozenset(
    {"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "PRODUCT", "SUBTOTAL"}
)


@dataclass(frozen=True, slots=True)
class RefEdge:
    source_sheet: str
    source_coordinate: str
    target: Reference
    via_defined_name: str | None = None


@dataclass(frozen=True, slots=True)
class AggregateRange:
    source_sheet: str
    source_coordinate: str
    function: str
    target: Reference


@dataclass(frozen=True, slots=True)
class RefGraph:
    edges: tuple[RefEdge, ...]
    aggregate_ranges: tuple[AggregateRange, ...]
    external_edges: tuple[RefEdge, ...]

    def outgoing(self, cell: Cell) -> tuple[RefEdge, ...]:
        return tuple(
            edge
            for edge in self.edges
            if edge.source_sheet == cell.sheet and edge.source_coordinate == cell.coordinate
        )


def _unquote_sheet(text: str) -> str:
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text


def _parse_reference(text: str, *, current_sheet: str) -> Reference:
    sheet_text, separator, coordinate = text.rpartition("!")
    sheet = _unquote_sheet(sheet_text) if separator else current_sheet
    coordinate = coordinate if separator else text
    external = "[" in sheet or "]" in sheet
    try:
        min_column, min_row, max_column, max_row = range_boundaries(coordinate)
    except ValueError:
        min_column = min_row = max_column = max_row = None
    return Reference(
        sheet=sheet,
        min_row=min_row,
        min_column=min_column,
        max_row=max_row,
        max_column=max_column,
        text=text,
        external=external,
    )


def build_reference_graph(workbook: Workbook) -> RefGraph:
    """Build cell, cross-sheet, external, named, and aggregate-range edges."""
    edges: list[RefEdge] = []
    aggregates: list[AggregateRange] = []

    for sheet in workbook.sheets:
        for cell in sheet.cells:
            if cell.formula is None:
                continue
            walk = walk_formula(cell.formula, workbook=workbook, sheet_index=sheet.index)
            for token in walk.range_tokens:
                defined_name = workbook.resolve_name(token.text, sheet_index=sheet.index)
                if defined_name is not None:
                    targets = defined_name.references
                    name = defined_name.name
                else:
                    targets = (_parse_reference(token.text, current_sheet=sheet.name),)
                    name = None
                for target in targets:
                    edge = RefEdge(
                        source_sheet=sheet.name,
                        source_coordinate=cell.coordinate,
                        target=target,
                        via_defined_name=name,
                    )
                    edges.append(edge)
                    if token.function in _AGGREGATE_FUNCTIONS:
                        aggregates.append(
                            AggregateRange(
                                source_sheet=sheet.name,
                                source_coordinate=cell.coordinate,
                                function=token.function,
                                target=target,
                            )
                        )

    edge_tuple = tuple(edges)
    return RefGraph(
        edges=edge_tuple,
        aggregate_ranges=tuple(aggregates),
        external_edges=tuple(edge for edge in edge_tuple if edge.target.external),
    )
