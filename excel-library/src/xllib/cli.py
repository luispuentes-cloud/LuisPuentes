"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from xllib.inspect import (
    estimate_section_count,
    infer_formula_runs,
    load_workbook,
    walk_formula,
)
from xllib.lint import lint, load_config
from xllib.lint.registry import registered_rules
from xllib.recalc import RecalcFailed, recalculate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xllib")
    commands = parser.add_subparsers(dest="command", required=True)
    lint_parser = commands.add_parser("lint", help="inspect and lint an .xlsx file")
    lint_parser.add_argument("path", type=Path)
    lint_parser.add_argument("--json", action="store_true", dest="as_json")
    lint_parser.add_argument("--measure", action="store_true")
    lint_parser.add_argument("--config", type=Path)
    return parser


def _measure(workbook: Any) -> dict[str, Any]:
    shapes: set[str] = set()
    max_depth = max_calls = 0
    defined_names = len(workbook.defined_names)
    sections = {}
    for sheet in workbook.sheets:
        sections[sheet.name] = estimate_section_count(sheet)
        for run in infer_formula_runs(sheet):
            shapes.update(run.shapes)
        for cell in sheet.cells:
            if cell.formula is None:
                continue
            walk = walk_formula(cell.formula, workbook=workbook, sheet_index=sheet.index)
            max_depth = max(max_depth, walk.max_function_depth)
            max_calls = max(max_calls, walk.function_count)
    return {
        "sheets": len(workbook.sheets),
        "sheet_states": {sheet.name: sheet.state for sheet in workbook.sheets},
        "estimated_sections": sections,
        "distinct_formula_shapes": len(shapes),
        "max_formula_depth": max_depth,
        "max_function_calls_per_cell": max_calls,
        "defined_names": defined_names,
    }


def _run_lint(args: argparse.Namespace) -> int:
    if args.measure:
        workbook = load_workbook(args.path)
        print(json.dumps(_measure(workbook), indent=2))
        return 0
    config_path = args.config
    if config_path is None:
        candidate = Path("xllib.toml")
        config_path = candidate if candidate.exists() else None
    config = load_config(config_path)
    try:
        with recalculate(args.path) as result:
            workbook = load_workbook(result.path)
            report = lint(workbook, config, registered_rules())
    except RecalcFailed:
        workbook = load_workbook(args.path)
        report = lint(workbook, config, registered_rules())
    print(report.to_json() if args.as_json else report.to_text())
    return report.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "lint":
            return _run_lint(args)
        return 3
    except (OSError, ValueError) as error:
        print(f"xllib: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
