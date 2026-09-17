"""Public read-only Excel inspection API."""

from .capability import Capability, capabilities
from .load import load_workbook
from .model import Cell, DefinedName, Reference, Sheet, Workbook
from .refs import AggregateRange, RefEdge, RefGraph, build_reference_graph
from .spans import (
    FormulaRun,
    PeriodAxis,
    detect_period_axes,
    detect_period_axis,
    estimate_section_count,
    infer_formula_runs,
)
from .tokens import (
    NumericLiteral,
    RangeToken,
    TokenWalk,
    normalize_formula_shape,
    walk_formula,
)

__all__ = [
    "AggregateRange",
    "Capability",
    "Cell",
    "DefinedName",
    "FormulaRun",
    "NumericLiteral",
    "PeriodAxis",
    "RangeToken",
    "RefEdge",
    "RefGraph",
    "Reference",
    "Sheet",
    "TokenWalk",
    "Workbook",
    "build_reference_graph",
    "capabilities",
    "detect_period_axes",
    "detect_period_axis",
    "estimate_section_count",
    "infer_formula_runs",
    "load_workbook",
    "normalize_formula_shape",
    "walk_formula",
]
