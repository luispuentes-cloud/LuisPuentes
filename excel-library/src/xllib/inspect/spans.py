"""Documented workbook-shape heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .model import Cell, Sheet
from .tokens import normalize_formula_shape

_PERIOD_LABEL = re.compile(
    r"^(?:FY\s*[-']?\s*\d{2,4}|"
    r"Q[1-4](?:\s*[-/']?\s*(?:FY)?\d{2,4})?|"
    r"(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|"
    r"JUL(?:Y)?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|OCT(?:OBER)?|"
    r"NOV(?:EMBER)?|DEC(?:EMBER)?)"
    r"[\s\-/']+\d{2,4})$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PeriodAxis:
    sheet: str
    row: int
    start_column: int
    end_column: int
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FormulaRun:
    sheet: str
    row: int
    start_column: int
    end_column: int
    coordinates: tuple[str, ...]
    shapes: tuple[str, ...]


def _period_label(cell: Cell) -> str | None:
    value = cell.effective_value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str):
        label = value.strip()
        if _PERIOD_LABEL.fullmatch(label):
            return label
    return None


def detect_period_axes(sheet: Sheet, *, minimum_periods: int = 2) -> tuple[PeriodAxis, ...]:
    """Detect contiguous horizontal runs of date-like period labels."""
    axes: list[PeriodAxis] = []
    for row_number in sheet.populated_rows:
        run: list[tuple[Cell, str]] = []
        for column_number in range(1, sheet.max_column + 2):
            cell = sheet.cell(row_number, column_number)
            if cell is not None and (label := _period_label(cell)) is not None:
                run.append((cell, label))
                continue
            if len(run) >= minimum_periods:
                axes.append(
                    PeriodAxis(
                        sheet=sheet.name,
                        row=row_number,
                        start_column=run[0][0].column,
                        end_column=run[-1][0].column,
                        labels=tuple(item[1] for item in run),
                    )
                )
            run = []
    return tuple(axes)


def detect_period_axis(sheet: Sheet, *, minimum_periods: int = 2) -> PeriodAxis | None:
    """Return the longest detected period axis on a worksheet."""
    axes = detect_period_axes(sheet, minimum_periods=minimum_periods)
    if not axes:
        return None
    return max(
        axes,
        key=lambda axis: (
            axis.end_column - axis.start_column,
            -axis.row,
            -axis.start_column,
        ),
    )


def infer_formula_runs(sheet: Sheet, *, minimum_cells: int = 2) -> tuple[FormulaRun, ...]:
    """Infer contiguous horizontal formula runs and record normalized shapes."""
    runs: list[FormulaRun] = []
    for row_number in sheet.populated_rows:
        run: list[Cell] = []
        for column_number in range(1, sheet.max_column + 2):
            cell = sheet.cell(row_number, column_number)
            if cell is not None and cell.formula is not None:
                run.append(cell)
                continue
            if len(run) >= minimum_cells:
                runs.append(
                    FormulaRun(
                        sheet=sheet.name,
                        row=row_number,
                        start_column=run[0].column,
                        end_column=run[-1].column,
                        coordinates=tuple(item.coordinate for item in run),
                        shapes=tuple(
                            normalize_formula_shape(
                                item.formula or "", row=item.row, column=item.column
                            )
                            for item in run
                        ),
                    )
                )
            run = []
    return tuple(runs)


def estimate_section_count(sheet: Sheet) -> int:
    """Estimate sections as non-empty row groups separated by blank rows.

    Counting the gaps between occupied rows rather than walking every row to
    `max_row` gives the same answer at a cost set by the content instead of by
    the sheet's declared height.
    """
    occupied_rows = sorted(
        {
            cell.row
            for cell in sheet.cells
            if cell.formula is not None or cell.effective_value is not None
        }
    )
    sections = 0
    previous_row: int | None = None
    for row_number in occupied_rows:
        if previous_row is None or row_number != previous_row + 1:
            sections += 1
        previous_row = row_number
    return sections
