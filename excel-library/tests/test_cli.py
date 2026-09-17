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
    assert output["distinct_formula_shapes"] == 0


def test_usage_or_load_failure_returns_three(tmp_path: Path) -> None:
    assert main(["lint", str(tmp_path / "missing.xlsx")]) == 3


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
