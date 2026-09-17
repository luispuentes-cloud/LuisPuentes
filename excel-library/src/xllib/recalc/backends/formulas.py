"""The `formulas` backend: pure Python, and the only one that runs in Linux CI.

Two quirks of `formulas` 1.3.4 are handled here and recorded in ADR-0004: its
solution keys upper-case the sheet name, and it drives a tqdm progress bar on
stderr that would otherwise mix into the CLI's own diagnostics.

Values are injected into a copy of the original workbook rather than written
out by `formulas` itself, so number formats and styles survive.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from ..backend import Availability, BackendError
from ..cache import EXCEL_ERRORS, write_cached_values

__all__ = ["FormulasBackend"]

# "'[MODEL.XLSX]CALC'!D7" — book, sheet, and a single cell. Range and defined
# name keys do not match and are left alone.
_SOLUTION_KEY = re.compile(
    r"^'?\[(?P<book>[^\]]+)\](?P<sheet>[^'!]+)'?!(?P<ref>[A-Za-z]{1,3}[0-9]{1,7})$"
)

_UNSET = object()


class FormulasBackend:
    """Evaluate a workbook with the `formulas` package."""

    name = "formulas"

    def available(self) -> Availability:
        if importlib.util.find_spec("formulas") is None:
            return Availability.unavailable(self.name, "the formulas package is not installed")
        return Availability.ok(self.name)

    def recalculate(self, path: Path) -> None:
        try:
            import formulas
        except ImportError as error:
            raise BackendError(self.name, "the formulas package is not importable") from error

        with _quiet_progress():
            model = formulas.ExcelModel().loads(str(path)).finish()
            solution = model.calculate()

        report = write_cached_values(path, _values_by_sheet(solution, path.name))
        if report.unwritten:
            sample = ", ".join(report.unwritten[:8])
            raise BackendError(
                self.name,
                f"partial cache write for {path.name}: {len(report.unwritten)} of "
                f"{report.formula_cells} formula cells have no cached value ({sample})",
            )


@contextlib.contextmanager
def _quiet_progress() -> Iterator[None]:
    """Swallow the tqdm progress bar `formulas` writes to stderr."""
    with contextlib.redirect_stderr(io.StringIO()):
        yield


def _values_by_sheet(solution: Any, book: str) -> dict[str, dict[str, Any]]:
    """Group a `formulas` solution into {sheet: {ref: value}}.

    Sheet names arrive upper-cased and stay that way; `write_cached_values`
    matches them case-insensitively. Keys belonging to another book — an
    external link — are dropped, because only this file is being rewritten.
    """
    values: dict[str, dict[str, Any]] = {}
    for key, raw in dict(solution).items():
        match = _SOLUTION_KEY.match(str(key))
        if match is None or match["book"].upper() != book.upper():
            continue
        value = _scalar(raw)
        if value is _UNSET:
            continue
        values.setdefault(match["sheet"].upper(), {})[match["ref"].upper()] = value
    return values


def _scalar(raw: Any, depth: int = 0) -> Any:
    """Unwrap a `formulas` cell result down to a plain Python scalar.

    Results arrive as range objects wrapping numpy arrays, numpy scalars, or
    error tokens. A computed blank (`None`) is kept so the injector can write
    an empty cache. Anything that does not reduce to one value — an array
    spill beyond the top-left cell, an unrecognised token — yields `_UNSET`
    and is left unwritten, which fails the backend's completeness check.
    """
    if depth > 4:
        return _UNSET
    if raw is None or type(raw) in (bool, int, float, str):
        return raw

    item = getattr(raw, "item", None)
    if callable(item):
        try:
            scalar = item()
        except ValueError:
            scalar = _UNSET
        if scalar is not _UNSET and scalar is not raw:
            return _scalar(scalar, depth + 1)

    inner = getattr(raw, "value", None)
    if inner is not None and inner is not raw:
        return _scalar(inner, depth + 1)

    as_list = getattr(raw, "tolist", None)
    if callable(as_list):
        flat = _flatten(as_list())
        return _scalar(flat[0], depth + 1) if len(flat) == 1 else _UNSET

    text = str(raw)
    return text if text in EXCEL_ERRORS else _UNSET


def _flatten(value: Any) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return [value]
    return [item for element in value for item in _flatten(element)]
