from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook as OpenpyxlWorkbook
from openpyxl.workbook.defined_name import DefinedName

from xllib.inspect import Capability, capabilities, load_workbook

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _set_formula_cache(path: Path, coordinate: str, value: str) -> None:
    with ZipFile(path, "r") as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    root = ET.fromstring(members["xl/worksheets/sheet1.xml"])
    cell = root.find(f".//{{{_MAIN_NS}}}c[@r='{coordinate}']")
    assert cell is not None
    cached = cell.find(f"{{{_MAIN_NS}}}v")
    if cached is None:
        cached = ET.SubElement(cell, f"{{{_MAIN_NS}}}v")
    cached.text = value
    members["xl/worksheets/sheet1.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_dual_load_pairs_formula_and_cached_value(tmp_path: Path) -> None:
    path = tmp_path / "cached.xlsx"
    book = OpenpyxlWorkbook()
    sheet = book.active
    sheet.title = "Calc"
    sheet["A1"] = 6
    sheet["B1"] = "=A1*7"
    book.save(path)
    _set_formula_cache(path, "B1", "42")

    inspected = load_workbook(path)
    calc = inspected.sheet("calc")
    assert calc is not None
    formula_cell = calc.cell(1, 2)

    assert formula_cell is not None
    assert formula_cell.formula == "=A1*7"
    assert formula_cell.cached_value == 42
    assert Capability.CACHED_VALUES in capabilities(inspected)


def test_load_preserves_hidden_states_and_defined_names(tmp_path: Path) -> None:
    path = tmp_path / "states.xlsx"
    book = OpenpyxlWorkbook()
    inputs = book.active
    inputs.title = "Inputs"
    inputs["B2"] = 0.85
    hidden = book.create_sheet("HiddenCalc")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "=DRIVER"
    very_hidden = book.create_sheet("Audit")
    very_hidden.sheet_state = "veryHidden"
    very_hidden["A1"] = "retained"
    book.defined_names.add(DefinedName("DRIVER", attr_text="'Inputs'!$B$2"))
    book.save(path)

    inspected = load_workbook(path)

    hidden_calc = inspected.sheet("HiddenCalc")
    assert hidden_calc is not None
    assert tuple(sheet.state for sheet in inspected.sheets) == (
        "visible",
        "hidden",
        "veryHidden",
    )
    hidden_formula = hidden_calc.cell(1, 1)
    assert hidden_formula is not None
    assert hidden_formula.formula == "=DRIVER"
    driver = inspected.resolve_name("driver", sheet_index=1)
    assert driver is not None
    assert driver.references[0].sheet == "Inputs"
    assert driver.references[0].is_single_cell


def test_missing_formula_cache_is_not_claimed(tmp_path: Path) -> None:
    path = tmp_path / "uncalculated.xlsx"
    book = OpenpyxlWorkbook()
    book.active["A1"] = "=1+1"
    book.save(path)

    inspected = load_workbook(path)

    assert Capability.CACHED_VALUES not in capabilities(inspected)
