from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from xllib.cli import main


def test_measure_emits_metrics_without_recalculation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "measure.xlsx"
    book = Workbook()
    sheet = book.active
    sheet["A1"] = 1
    sheet["B1"] = "=A1"
    book.save(path)

    assert main(["lint", str(path), "--measure"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["sheets"] == 1
    # Was asserted as 0, which enshrined the undercount: the sheet holds one
    # formula, so one distinct shape is the only defensible answer.
    assert output["formula_cells"] == 1
    assert output["distinct_formula_shapes"] == 1


def test_measure_counts_shapes_outside_inferred_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Seven distinct formulas, none adjacent to another. The answer is seven.

    Shape collection ran off `infer_formula_runs`, which needs two adjacent
    formula cells in a row, so isolated formulas were never counted. This is
    the fixture the review described: it measured 2.
    """
    path = tmp_path / "isolated.xlsx"
    book = Workbook()
    sheet = book.active
    for row in range(1, 8):
        sheet.cell(row=row, column=1, value=row)
    # Column C, with column B left empty so no two formulas are ever adjacent.
    formulas = ["=A1", "=A2*2", "=SUM(A1:A3)", "=A4+A5", "=MAX(A1:A7)", "=A6/A7", "=-A7"]
    for row, formula in enumerate(formulas, start=1):
        sheet.cell(row=row, column=3, value=formula)
    book.save(path)

    assert main(["lint", str(path), "--measure"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["formula_cells"] == 7
    assert output["distinct_formula_shapes"] == 7


def test_usage_or_load_failure_returns_three(tmp_path: Path) -> None:
    assert main(["lint", str(tmp_path / "missing.xlsx")]) == 3


def test_a_corrupt_zip_returns_three(tmp_path: Path) -> None:
    """Exit 3 was only ever tested with a missing file, which is an `OSError`.

    A truncated or corrupt `.xlsx` is a `zipfile.BadZipFile`, which inherits
    from `Exception` and not from `OSError`, so it fell outside the pair the
    CLI catches and reached the user as a traceback.
    """
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(b"PK\x03\x04 truncated, not a workbook")
    assert main(["lint", str(path)]) == 3


def test_a_legacy_xls_returns_three(tmp_path: Path) -> None:
    """openpyxl raises `InvalidFileException`, also outside `OSError`/`ValueError`.

    Someone pointing the linter at a `.xls` is the likeliest real encounter
    with an unreadable file, and it should say so rather than crash.
    """
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(64))
    assert main(["lint", str(path)]) == 3


def test_lint_recalculates_and_emits_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "lint.xlsx"
    book = Workbook()
    sheet = book.active
    sheet["A1"] = 10
    sheet["B1"] = "=A1*0.85"
    book.save(path)

    assert main(["lint", str(path), "--json"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["error"] >= 1
    assert output["summary"]["skipped"] == 0
    assert any(item["rule_id"] == "XL002" for item in output["findings"])
