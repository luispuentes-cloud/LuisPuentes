from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from xllib import cli
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


def test_an_unreadable_file_is_refused_before_recalculation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 3 on its own does not prove the guard ran.

    An independent bite-test on 2026-09-22 reverted the `assert_readable` call
    and both exit-3 tests still passed: the file reached the recalc chain and
    came back as exit 3 from the `UNREADABLE` handler seventy seconds later.
    The exit code is identical either way, so it cannot distinguish them. What
    the guard exists to prevent is handing an unreadable file to backends
    ending in Excel COM, which ended the process with an access violation —
    so the thing to assert is that recalculation is never reached at all.
    """
    reached = False

    def _never_recalculate(*_: object, **__: object) -> object:
        nonlocal reached
        reached = True
        raise AssertionError("recalculate was reached for a file openpyxl cannot read")

    monkeypatch.setattr(cli, "recalculate", _never_recalculate)
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(b"PK\x03\x04 truncated, not a workbook")

    assert main(["lint", str(path)]) == 3
    assert not reached


def test_a_legacy_xls_returns_three(tmp_path: Path) -> None:
    """openpyxl raises `InvalidFileException`, also outside `OSError`/`ValueError`.

    Someone pointing the linter at a `.xls` is the likeliest real encounter
    with an unreadable file, and it should say so rather than crash.
    """
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(64))
    assert main(["lint", str(path)]) == 3


def test_a_zip_that_is_not_a_workbook_returns_three(tmp_path: Path) -> None:
    """A valid zip named `.xlsx` is not the same as a workbook.

    Corrupt-zip coverage used a truncated archive (`BadZipFile`). This is the
    other common encounter: a well-formed zip that is not Office Open XML.
    """
    path = tmp_path / "not-a-workbook.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "not an office document")
    assert main(["lint", str(path)]) == 3


def test_a_password_protected_file_returns_three(tmp_path: Path) -> None:
    """Encrypted `.xlsx` is an OLE compound file, not a zip.

    Excel's password-protected OOXML wrapper uses the same CFB signature as a
    legacy `.xls`. Named separately so a later reader does not treat the
    `.xls` case as the only OLE path that matters.
    """
    path = tmp_path / "encrypted.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(64))
    assert main(["lint", str(path)]) == 3


def test_the_module_entry_point_reaches_the_cli(tmp_path: Path) -> None:
    """`python -m xllib` is what the skills tell a consultant to run.

    Calling `main()` directly cannot prove it: the package resolved and the
    CLI worked long before `__main__.py` existed, and `python -m xllib` still
    failed with "is a package and cannot be directly executed". Only a
    subprocess exercises the entry point. `--measure` is used so the check
    costs no recalculation.

    `PYTHONPATH` carries this tree's `src` for the same reason `conftest.py`
    prepends it in-process: a bare subprocess resolves `xllib` from whatever
    is pip-installed, which on this machine is a different checkout entirely.
    Without it the test reports on that checkout rather than on this one.
    """
    path = tmp_path / "entry.xlsx"
    book = Workbook()
    sheet = book.active
    sheet["A1"] = 10
    sheet["B1"] = "=A1*0.85"
    book.save(path)

    src = Path(__file__).resolve().parents[1] / "src"
    completed = subprocess.run(
        [sys.executable, "-m", "xllib", "lint", str(path), "--measure"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(src)},
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["formula_cells"] == 1


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
