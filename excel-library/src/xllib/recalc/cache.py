"""Write cached formula results into an existing .xlsx.

openpyxl cannot hold a formula and its value in the same cell, and rewriting a
workbook through openpyxl would drop the number formats that rules XL004 and
XL104 read. So a pure-Python backend computes values and this module injects
them into the sheet XML of the workbook it already has, leaving every other
part of the package byte-identical.

Backends that drive a real spreadsheet application (LibreOffice, Excel) save
their own cached values and do not need this.
"""

from __future__ import annotations

import os
import posixpath
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import isfinite
from pathlib import Path
from typing import Any

from openpyxl.utils.datetime import time_to_days, timedelta_to_days, to_excel

__all__ = ["EXCEL_ERRORS", "CacheReport", "write_cached_values"]

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

_CELL = f"{{{_MAIN}}}c"
_FORMULA = f"{{{_MAIN}}}f"
_VALUE = f"{{{_MAIN}}}v"
_INLINE = f"{{{_MAIN}}}is"

EXCEL_ERRORS = frozenset(
    {
        "#CALC!",
        "#DIV/0!",
        "#GETTING_DATA",
        "#N/A",
        "#NAME?",
        "#NULL!",
        "#NUM!",
        "#REF!",
        "#SPILL!",
        "#VALUE!",
    }
)

# Keeps the rewritten sheet XML using the prefixes Excel itself writes.
for _prefix, _uri in (
    ("", _MAIN),
    ("r", _DOC_REL),
    ("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006"),
    ("x14ac", "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"),
):
    ET.register_namespace(_prefix, _uri)


@dataclass(frozen=True, slots=True)
class CacheReport:
    """What an injection pass found and did.

    `formula_cells` counts every formula cell in the workbook, not only the
    ones a value was supplied for, so a backend can tell "this workbook has no
    formulas" apart from "this backend computed nothing".
    """

    formula_cells: int
    written: int
    unmatched_sheets: tuple[str, ...]
    unwritten: tuple[str, ...]


def write_cached_values(path: Path, values: Mapping[str, Mapping[str, Any]]) -> CacheReport:
    """Inject `values` into the formula cells of `path`, in place.

    `values` is keyed by sheet name and then by A1 reference. Both are matched
    case-insensitively: `formulas` uppercases sheet names in its solution keys
    (`Calc` becomes `CALC`), per ADR-0004. References that name a cell holding
    no formula, and values of a type that has no cached representation, are
    skipped rather than guessed at.
    """
    wanted = {
        sheet.upper(): {ref.upper(): value for ref, value in cells.items()}
        for sheet, cells in values.items()
    }

    replacements: dict[str, bytes] = {}
    formula_cells = 0
    written = 0
    unwritten: list[str] = []

    with zipfile.ZipFile(path) as archive:
        parts = _sheet_parts(archive)
        for sheet, part in parts.items():
            root = ET.fromstring(archive.read(part))
            patched, seen, missing = _patch_sheet(root, wanted.get(sheet, {}))
            formula_cells += seen
            written += patched
            unwritten.extend(f"{sheet}!{ref}" for ref in missing)
            if patched:
                replacements[part] = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
        unmatched = tuple(sorted(sheet for sheet in wanted if sheet not in parts))

    if replacements:
        _rewrite_archive(path, replacements)

    return CacheReport(
        formula_cells=formula_cells,
        written=written,
        unmatched_sheets=unmatched,
        unwritten=tuple(unwritten),
    )


def _sheet_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    """Map upper-cased sheet name to the archive member holding that sheet."""
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        element.get("Id"): element.get("Target")
        for element in rels.findall(f"{{{_PKG_REL}}}Relationship")
    }

    parts: dict[str, str] = {}
    for sheet in workbook.findall(f"./{{{_MAIN}}}sheets/{{{_MAIN}}}sheet"):
        name = sheet.get("name")
        target = targets.get(sheet.get(f"{{{_DOC_REL}}}id"))
        if name is None or target is None:
            continue
        parts[name.upper()] = _resolve_part(target)
    return parts


def _resolve_part(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def _patch_sheet(root: ET.Element, cells: Mapping[str, Any]) -> tuple[int, int, tuple[str, ...]]:
    """Return (values written, formula cells seen, unwritten refs) for one sheet.

    A key present with value `None` is a computed blank and is written. A
    missing key, or a value with no cached representation, is left unwritten.
    """
    written = 0
    seen = 0
    missing: list[str] = []
    for cell in root.iter(_CELL):
        formula = cell.find(_FORMULA)
        if formula is None:
            continue
        seen += 1
        ref = (cell.get("r") or "").upper()
        if ref not in cells:
            missing.append(ref)
            continue
        encoded = _encode(cells[ref])
        if encoded is None:
            missing.append(ref)
            continue
        _set_cached_value(cell, formula, encoded)
        written += 1
    return written, seen, tuple(missing)


def _set_cached_value(
    cell: ET.Element, formula: ET.Element, encoded: tuple[str | None, str]
) -> None:
    for child in [c for c in cell if c.tag in (_VALUE, _INLINE)]:
        cell.remove(child)

    cell_type, text = encoded
    if cell_type is None:
        cell.attrib.pop("t", None)
    else:
        cell.set("t", cell_type)

    value = ET.Element(_VALUE)
    value.text = text
    cell.insert(list(cell).index(formula) + 1, value)


def _encode(value: Any) -> tuple[str | None, str] | None:
    """Encode `value` as a (cell type, text) pair, or None if it has no cached form.

    Numbers are coerced through `int`/`float` before being rendered, because
    subclasses can carry a repr that is not a number at all: numpy 2 renders
    `np.float64(6.0)` that way, and writing it would produce a workbook no
    reader accepts.
    """
    if value is None:
        return ("str", "")
    if isinstance(value, bool):
        return ("b", "1" if value else "0")
    if isinstance(value, int):
        return (None, str(int(value)))
    if isinstance(value, float):
        return (None, repr(float(value))) if isfinite(value) else ("e", "#NUM!")
    if isinstance(value, Decimal):
        return _encode(float(value))
    if isinstance(value, datetime | date):
        return (None, repr(float(to_excel(value))))
    if isinstance(value, time):
        return (None, repr(float(time_to_days(value))))
    if isinstance(value, timedelta):
        return (None, repr(float(timedelta_to_days(value))))
    if isinstance(value, str):
        text = str(value)
        return ("e", text) if text in EXCEL_ERRORS else ("str", text)
    return None


def _rewrite_archive(path: Path, replacements: Mapping[str, bytes]) -> None:
    """Replace members of `path` atomically, preserving every other member."""
    staged = path.with_name(f"{path.name}.xllib-recalc")
    try:
        with (
            zipfile.ZipFile(path) as source,
            zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as target,
        ):
            for item in source.infolist():
                data = replacements.get(item.filename)
                if data is None:
                    data = source.read(item.filename)
                copied = zipfile.ZipInfo(item.filename, date_time=item.date_time)
                copied.compress_type = item.compress_type
                copied.create_system = item.create_system
                copied.external_attr = item.external_attr
                copied.internal_attr = item.internal_attr
                target.writestr(copied, data)
        os.replace(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
