"""Read-only workbook inspection intermediate representation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType

type Scalar = str | int | float | bool | date | datetime | time | timedelta
type CellValue = Scalar | None

#: Excel stores an error as a string, so `isinstance(value, str)` is true of
#: `#DIV/0!` as well as of "not applicable". A rule that does not separate the
#: two calls a broken formula a formatting problem.
ERROR_LITERALS = frozenset(
    {
        "#BLOCKED!",
        "#BUSY!",
        "#CALC!",
        "#CONNECT!",
        "#DIV/0!",
        "#FIELD!",
        "#GETTING_DATA",
        "#N/A",
        "#NAME?",
        "#NULL!",
        "#NUM!",
        "#REF!",
        "#SPILL!",
        "#UNKNOWN!",
        "#VALUE!",
    }
)


@dataclass(frozen=True, slots=True)
class Cell:
    """A cell paired across formula and cached-value workbook loads."""

    sheet: str
    row: int
    column: int
    coordinate: str
    value: CellValue
    formula: str | None
    cached_value: CellValue
    data_type: str
    number_format: str
    has_style: bool
    has_font: bool
    has_fill: bool

    @property
    def effective_value(self) -> CellValue:
        """Return the cached result for formulas and the stored value otherwise."""
        return self.cached_value if self.formula is not None else self.value

    @property
    def is_error(self) -> bool:
        """True when the effective value is an Excel error rather than text.

        The literal is matched exactly and then corroborated against the file's
        own type system: a formula's cached result, or a static cell Excel
        typed `e`. Normalising case and whitespace here would only ever add
        matches the file does not claim, which is how the text " #n/a " came to
        be reported as a broken formula.
        """
        value = self.effective_value
        if not isinstance(value, str) or value not in ERROR_LITERALS:
            return False
        return self.formula is not None or self.data_type == "e"

    @property
    def cache_missing(self) -> bool:
        """True when a formula cell has no cached result at all.

        A computed blank is stored as an empty string by the recalc injector, so
        `cached_value is None` on a formula cell means the cache was never
        written. Excel-saved blanks and missing caches can still coincide as
        None; that remaining ambiguity is documented, not guessed at.
        """
        return self.formula is not None and self.cached_value is None


@dataclass(frozen=True, slots=True)
class Sheet:
    """A worksheet, including its original visibility state."""

    name: str
    index: int
    state: str
    max_row: int
    max_column: int
    cells: tuple[Cell, ...]
    _by_position: Mapping[tuple[int, int], Cell]

    def cell(self, row: int, column: int) -> Cell | None:
        return self._by_position.get((row, column))

    @classmethod
    def create(
        cls,
        *,
        name: str,
        index: int,
        state: str,
        max_row: int,
        max_column: int,
        cells: tuple[Cell, ...],
    ) -> Sheet:
        positions = MappingProxyType({(cell.row, cell.column): cell for cell in cells})
        return cls(name, index, state, max_row, max_column, cells, positions)


@dataclass(frozen=True, slots=True)
class Reference:
    """A rectangular workbook reference."""

    sheet: str | None
    min_row: int | None
    min_column: int | None
    max_row: int | None
    max_column: int | None
    text: str
    external: bool = False

    @property
    def is_single_cell(self) -> bool:
        return (
            self.min_row is not None
            and self.min_row == self.max_row
            and self.min_column is not None
            and self.min_column == self.max_column
        )


@dataclass(frozen=True, slots=True)
class DefinedName:
    """A workbook- or worksheet-scoped defined name."""

    name: str
    local_sheet_id: int | None
    hidden: bool
    expression: str
    references: tuple[Reference, ...]


@dataclass(frozen=True, slots=True)
class Workbook:
    """The complete inspection representation of a workbook."""

    path: Path
    sheets: tuple[Sheet, ...]
    defined_names: tuple[DefinedName, ...]
    _sheets_by_name: Mapping[str, Sheet]

    @classmethod
    def create(
        cls,
        *,
        path: Path,
        sheets: tuple[Sheet, ...],
        defined_names: tuple[DefinedName, ...],
    ) -> Workbook:
        by_name = MappingProxyType({sheet.name.casefold(): sheet for sheet in sheets})
        return cls(path, sheets, defined_names, by_name)

    def sheet(self, name: str) -> Sheet | None:
        return self._sheets_by_name.get(name.casefold())

    def resolve_name(self, name: str, *, sheet_index: int | None = None) -> DefinedName | None:
        folded = name.casefold()
        if sheet_index is not None:
            for defined_name in self.defined_names:
                if (
                    defined_name.name.casefold() == folded
                    and defined_name.local_sheet_id == sheet_index
                ):
                    return defined_name
        for defined_name in self.defined_names:
            if defined_name.name.casefold() == folded and defined_name.local_sheet_id is None:
                return defined_name
        return None
