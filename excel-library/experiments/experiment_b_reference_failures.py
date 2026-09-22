"""Build the three experiment B fixtures in Excel, then render them to PNG.

Excel COM, not openpyxl, and the reason is not stylistic. `CACHED_VALUES` is
all-or-nothing: a workbook holding any uncalculated formula makes the linter
skip XL004, XL005 and XL103 across the whole file, so a clean result from an
openpyxl-authored fixture would be a clean result from rules that never ran.

Lives in `experiments/`, not `tests/`. It needs desktop Excel and can never
run in Linux CI. See `docs/EXPERIMENT_B.md` for the registered decision rule.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

XL_OPENXML_WORKBOOK = 51
XL_BITMAP = 2
XL_SCREEN = 1

INPUT_FONT = 16711680  # RGB(0, 0, 255) — COM packs colour as BGR.
INPUT_FILL = 13434879  # RGB(255, 255, 204)


def _input(cell: Any, value: float, number_format: str) -> None:
    """Write a driver cell with redundant styling, as XL104 requires."""
    cell.Value = value
    cell.NumberFormat = number_format
    cell.Font.Color = INPUT_FONT
    cell.Interior.Color = INPUT_FILL


def _title(cell: Any, text: str) -> None:
    cell.Value = text
    cell.Font.Bold = True


def build_b1(excel: Any, out: Path) -> Path:
    """Off-sheet driver reached by plain cell reference. No defined name."""
    book = excel.Workbooks.Add()
    while book.Worksheets.Count > 2:
        book.Worksheets(book.Worksheets.Count).Delete()
    while book.Worksheets.Count < 2:
        book.Worksheets.Add(After=book.Worksheets(book.Worksheets.Count))

    drivers = book.Worksheets(1)
    drivers.Name = "Drivers"
    _title(drivers.Range("A1"), "Drivers")
    drivers.Range("A3").Value = "Adoption rate"
    _input(drivers.Range("B3"), 0.85, "0%")
    drivers.Range("A4").Value = "Hours saved per user"
    _input(drivers.Range("B4"), 120, "#,##0")
    drivers.Range("A5").Value = "Blended hourly rate"
    _input(drivers.Range("B5"), 65, '$#,##0.00')
    drivers.Columns("A").ColumnWidth = 24

    summary = book.Worksheets(2)
    summary.Name = "Summary"
    _title(summary.Range("A1"), "Summary")
    summary.Range("A3").Value = "Annual benefit"
    summary.Range("B3").Formula = "=Drivers!B3*Drivers!B4*Drivers!B5"
    summary.Range("B3").NumberFormat = '$#,##0'
    summary.Columns("A").ColumnWidth = 24

    path = out / "b1_offsheet_driver_no_named_range.xlsx"
    book.SaveAs(str(path), FileFormat=XL_OPENXML_WORKBOOK)
    _export(summary, "A1:C5", out / "b1_summary.png")
    _export(drivers, "A1:C6", out / "b1_drivers.png")
    book.Close(SaveChanges=False)
    return path


def build_b2a(excel: Any, out: Path) -> Path:
    """Control: adjacent parallel columns whose formula shapes differ."""
    book = excel.Workbooks.Add()
    while book.Worksheets.Count > 1:
        book.Worksheets(book.Worksheets.Count).Delete()

    sheet = book.Worksheets(1)
    sheet.Name = "Benefits"
    _title(sheet.Range("A1"), "Annual benefit by lever")
    _title(sheet.Range("B3"), "Automation")
    _title(sheet.Range("C3"), "Vendor consolidation")
    sheet.Range("A4").Value = "Hours saved"
    _input(sheet.Range("B4"), 1200, "#,##0")
    _input(sheet.Range("C4"), 1200, "#,##0")
    sheet.Range("A5").Value = "Blended rate"
    _input(sheet.Range("B5"), 45, '$#,##0')
    _input(sheet.Range("C5"), 45, '$#,##0')
    sheet.Range("A6").Value = "Uplift factor"
    _input(sheet.Range("C6"), 0.12, "0%")
    sheet.Range("A7").Value = "Annual benefit"
    sheet.Range("B7").Formula = "=B4*B5"
    sheet.Range("C7").Formula = "=C4*C5*C6"
    sheet.Range("B7:C7").NumberFormat = '$#,##0'
    sheet.Columns("A").ColumnWidth = 20
    sheet.Columns("B:C").ColumnWidth = 20

    path = out / "b2a_adjacent_columns_different_shapes.xlsx"
    book.SaveAs(str(path), FileFormat=XL_OPENXML_WORKBOOK)
    _export(sheet, "A1:C8", out / "b2a_benefits.png")
    book.Close(SaveChanges=False)
    return path


def build_b2b(excel: Any, out: Path) -> Path:
    """Test: adjacent parallel columns, identical shape, different mechanics.

    Column B is bottom-up (hours x rate). Column C is top-down (a percentage
    of baseline spend). The row labels are the left column's, which is what a
    modeller produces when two calculations get forced into one table.
    """
    book = excel.Workbooks.Add()
    while book.Worksheets.Count > 1:
        book.Worksheets(book.Worksheets.Count).Delete()

    sheet = book.Worksheets(1)
    sheet.Name = "Benefits"
    _title(sheet.Range("A1"), "Annual benefit by lever")
    _title(sheet.Range("B3"), "Automation")
    _title(sheet.Range("C3"), "Vendor consolidation")
    sheet.Range("A4").Value = "Hours saved"
    _input(sheet.Range("B4"), 1200, "#,##0")
    _input(sheet.Range("C4"), 0.085, "0.0%")
    sheet.Range("A5").Value = "Blended rate"
    _input(sheet.Range("B5"), 45, '$#,##0')
    _input(sheet.Range("C5"), 640000, '$#,##0')
    sheet.Range("A6").Value = "Annual benefit"
    sheet.Range("B6").Formula = "=B4*B5"
    sheet.Range("C6").Formula = "=C4*C5"
    sheet.Range("B6:C6").NumberFormat = '$#,##0'
    sheet.Columns("A").ColumnWidth = 20
    sheet.Columns("B:C").ColumnWidth = 20

    path = out / "b2b_adjacent_columns_same_shape.xlsx"
    book.SaveAs(str(path), FileFormat=XL_OPENXML_WORKBOOK)
    _export(sheet, "A1:C7", out / "b2b_benefits.png")
    book.Close(SaveChanges=False)
    return path


def _export(sheet: Any, ref: str, png: Path) -> None:
    """Render a range to PNG so the reader-harm question can be looked at.

    The decision rule turns on whether a reader is genuinely harmed, which is a
    judgement about a rendered sheet. Asserting it from the source would be the
    thing this experiment exists to avoid.

    The clipboard round-trip needs the sheet activated and a beat to settle;
    without both, `Export` writes a ~200-byte empty PNG and reports success.
    The size floor below turns that silent failure into a visible one.
    """
    try:
        sheet.Activate()
        target = sheet.Range(ref)
        target.CopyPicture(Appearance=XL_SCREEN, Format=XL_BITMAP)
        time.sleep(1.0)
        chart = sheet.ChartObjects().Add(0, 0, target.Width + 8, target.Height + 8)
        chart.Activate()
        chart.Chart.ChartArea.Border.LineStyle = 0
        chart.Chart.Paste()
        time.sleep(0.5)
        chart.Chart.Export(str(png))
        chart.Delete()
    except Exception as error:
        # Broad on purpose: a clipboard or chart failure must not cost the
        # fixture, which is the artifact the experiment actually needs.
        print(f"  render failed for {png.name}: {error}", file=sys.stderr)
        return
    size = png.stat().st_size if png.exists() else 0
    if size < 2000:
        print(f"  render suspect for {png.name}: {size} bytes, likely blank", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("TEMP", ".")) / "xllib_experiment_b",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    import win32com.client

    excel = win32com.client.DispatchEx("Excel.Application")
    # Visible, deliberately: the CopyPicture clipboard round-trip is unreliable
    # against a hidden instance and fails by writing a blank PNG, not by raising.
    excel.Visible = True
    excel.DisplayAlerts = False
    try:
        for builder in (build_b1, build_b2a, build_b2b):
            path = builder(excel, args.out)
            print(f"built {path}")
    finally:
        excel.Quit()
    print(f"\noutput directory: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
