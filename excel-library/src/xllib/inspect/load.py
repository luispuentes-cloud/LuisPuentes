"""Dual-load Excel workbooks into the inspection IR."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from openpyxl import load_workbook as openpyxl_load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.workbook.defined_name import DefinedName as OpenpyxlDefinedName

from .model import Cell, DefinedName, Reference, Sheet, Workbook

_DEFAULT_RGB = frozenset({"00000000", "FF000000", "000000"})


def _has_font(cell: Any) -> bool:
    font = getattr(cell, "font", None)
    if font is None:
        return False
    if font.bold or font.italic or (font.underline not in (None, "none")):
        return True
    color = font.color
    if color is None:
        return False
    color_type = getattr(color, "type", None)
    if color_type == "rgb":
        rgb = str(color.rgb or "").upper()
        return bool(rgb) and rgb not in _DEFAULT_RGB
    if color_type == "theme":
        return color.theme not in (None, 0, 1)
    return False


def _has_fill(cell: Any) -> bool:
    fill = getattr(cell, "fill", None)
    if fill is None:
        return False
    return fill.fill_type not in (None, "none")


def _reference(sheet_name: str, coordinate: str) -> Reference:
    external = "[" in sheet_name or "]" in sheet_name
    try:
        min_column, min_row, max_column, max_row = range_boundaries(coordinate)
    except ValueError:
        min_column = min_row = max_column = max_row = None
    return Reference(
        sheet=sheet_name,
        min_row=min_row,
        min_column=min_column,
        max_row=max_row,
        max_column=max_column,
        text=f"{sheet_name}!{coordinate}",
        external=external,
    )


def _convert_defined_name(
    item: OpenpyxlDefinedName, *, default_local_sheet_id: int | None = None
) -> DefinedName:
    references: list[Reference] = []
    with suppress(AttributeError, TypeError, ValueError):
        references.extend(
            _reference(sheet_name, coordinate) for sheet_name, coordinate in item.destinations
        )
    return DefinedName(
        name=item.name,
        local_sheet_id=(
            item.localSheetId if item.localSheetId is not None else default_local_sheet_id
        ),
        hidden=bool(item.hidden),
        expression=item.attr_text or "",
        references=tuple(references),
    )


def _defined_names(formula_book: Any) -> tuple[DefinedName, ...]:
    names: list[DefinedName] = []
    seen: set[tuple[str, int | None]] = set()

    global_values: Iterable[OpenpyxlDefinedName] = formula_book.defined_names.values()
    for item in global_values:
        converted = _convert_defined_name(item)
        key = (converted.name.casefold(), converted.local_sheet_id)
        if key not in seen:
            names.append(converted)
            seen.add(key)

    for sheet_index, worksheet in enumerate(formula_book.worksheets):
        local_values: Iterable[OpenpyxlDefinedName] = worksheet.defined_names.values()
        for item in local_values:
            converted = _convert_defined_name(item, default_local_sheet_id=sheet_index)
            key = (converted.name.casefold(), converted.local_sheet_id)
            if key not in seen:
                names.append(converted)
                seen.add(key)
    return tuple(names)


def assert_readable(path: str | Path) -> None:
    """Raise if openpyxl cannot read this file, without parsing the whole thing.

    Callers that recalculate need this *before* handing the path on. The recalc
    chain copies the target and offers it to backends ending in Excel COM, so
    an unsupported or corrupt file otherwise gets launched in Excel — which
    took the process down with an access violation rather than returning a
    diagnosable exit code.

    `read_only=True` runs openpyxl's own extension and archive validation and
    stops short of reading cells, so a valid workbook is not parsed twice.

    A well-formed zip that is not OOXML raises `KeyError` for
    `[Content_Types].xml`. That is not an `OSError`, not a `BadZipFile`, and
    not `InvalidFileException`, so leaving it uncaught sent the user a
    traceback at exit 1 rather than exit 3.
    """
    source = Path(path)
    try:
        openpyxl_load_workbook(source, read_only=True).close()
    except KeyError as exc:
        raise ValueError(f"not a workbook: {source}") from exc


def _stored_cells(sheet: Any) -> list[Any]:
    """The cells the file actually stores, in row-major order.

    `iter_rows()` walks the *declared* rectangle and creates a cell object for
    every empty coordinate inside it. One stray value in the far corner of a
    sheet therefore costs the whole rectangle rather than the content: measured
    on openpyxl 3.1, a value at row 2000 column 200 turned 2 real cells into
    400,000 materialised ones in 0.8s. The regression fixture is a decade
    larger at 20,000 by 500, and took 364 seconds to read before this change
    against under a second after it. A full sheet exhausts memory rather than
    finishing. Phase 0 promises to run on an arbitrary `.xlsx`, and a
    far-corner cell is a common file shape rather than a contrived one.

    Every coordinate that walk invented was then discarded by the empty-and-
    unstyled test below, so reading openpyxl's own mapping of the cells that
    exist returns the same set for a cost set by the content. `_cells` is
    private, hence the fallback; `tests/test_inspect_load.py` pins the two
    routes to the same result.
    """
    stored: dict[tuple[int, int], Any] | None = getattr(sheet, "_cells", None)
    if stored is None:  # pragma: no cover - openpyxl always defines it today
        return [cell for row in sheet.iter_rows() for cell in row]
    return [stored[key] for key in sorted(stored)]


def load_workbook(path: str | Path, *, keep_links: bool = True) -> Workbook:
    """Load formulas and cached results, preserving every worksheet state."""
    source = Path(path)
    formula_book = openpyxl_load_workbook(
        source, data_only=False, read_only=False, keep_links=keep_links
    )
    value_book = openpyxl_load_workbook(
        source, data_only=True, read_only=False, keep_links=keep_links
    )
    try:
        sheets: list[Sheet] = []
        for index, formula_sheet in enumerate(formula_book.worksheets):
            value_sheet = value_book[formula_sheet.title]
            cells: list[Cell] = []
            for source_cell in _stored_cells(formula_sheet):
                cached_cell = value_sheet[source_cell.coordinate]
                has_font = _has_font(source_cell)
                has_fill = _has_fill(source_cell)
                if (
                    source_cell.value is None
                    and cached_cell.value is None
                    and not source_cell.has_style
                    and not has_font
                    and not has_fill
                ):
                    continue
                formula = (
                    source_cell.value
                    if source_cell.data_type == "f" and isinstance(source_cell.value, str)
                    else None
                )
                cells.append(
                    Cell(
                        sheet=formula_sheet.title,
                        row=source_cell.row,
                        column=source_cell.column,
                        coordinate=source_cell.coordinate,
                        value=None if formula is not None else source_cell.value,
                        formula=formula,
                        cached_value=(
                            cached_cell.value if formula is not None else source_cell.value
                        ),
                        data_type=source_cell.data_type,
                        number_format=source_cell.number_format,
                        has_style=source_cell.has_style,
                        has_font=has_font,
                        has_fill=has_fill,
                    )
                )
            sheets.append(
                Sheet.create(
                    name=formula_sheet.title,
                    index=index,
                    state=formula_sheet.sheet_state,
                    max_row=formula_sheet.max_row,
                    max_column=formula_sheet.max_column,
                    cells=tuple(cells),
                )
            )
        return Workbook.create(
            path=source,
            sheets=tuple(sheets),
            defined_names=_defined_names(formula_book),
        )
    finally:
        formula_book.close()
        value_book.close()
