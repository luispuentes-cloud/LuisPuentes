"""Flat, stateful formula-token inspection without an AST."""

from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl.formula.tokenizer import Token, Tokenizer
from openpyxl.utils.cell import column_index_from_string

from .model import Workbook

_CELL_REF = re.compile(
    r"(?<![A-Z0-9_.])(?P<colabs>\$?)(?P<col>[A-Z]{1,3})"
    r"(?P<rowabs>\$?)(?P<row>[1-9][0-9]*)(?![A-Z0-9_.])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NumericLiteral:
    text: str
    value: float
    function: str | None
    function_depth: int
    argument_index: int | None


@dataclass(frozen=True, slots=True)
class RangeToken:
    text: str
    function: str | None
    function_depth: int
    argument_index: int | None
    defined_name: str | None


@dataclass(frozen=True, slots=True)
class TokenWalk:
    formula: str
    numeric_literals: tuple[NumericLiteral, ...]
    range_tokens: tuple[RangeToken, ...]
    max_function_depth: int
    function_count: int


@dataclass(slots=True)
class _Frame:
    name: str
    argument_index: int = 0


def walk_formula(
    formula: str,
    *,
    workbook: Workbook | None = None,
    sheet_index: int | None = None,
) -> TokenWalk:
    """Walk openpyxl tokens and expose Phase 0 formula measurements."""
    if not formula.startswith("="):
        raise ValueError("formula must start with '='")

    frames: list[_Frame] = []
    numeric_literals: list[NumericLiteral] = []
    range_tokens: list[RangeToken] = []
    function_count = 0
    max_depth = 0
    previous: Token | None = None

    for token in Tokenizer(formula).items:
        if token.type == Token.FUNC and token.subtype == Token.OPEN:
            frames.append(_Frame(token.value.removesuffix("(").upper()))
            function_count += 1
            max_depth = max(max_depth, len(frames))
        elif token.type == Token.FUNC and token.subtype == Token.CLOSE:
            if frames:
                frames.pop()
        elif token.type == Token.SEP and token.subtype == Token.ARG:
            if frames:
                frames[-1].argument_index += 1
        elif token.type == Token.OPERAND and token.subtype == Token.NUMBER:
            sign = (
                "-"
                if previous is not None and previous.type == Token.OP_PRE and previous.value == "-"
                else ""
            )
            text = f"{sign}{token.value}"
            numeric_literals.append(
                NumericLiteral(
                    text=text,
                    value=float(text),
                    function=frames[-1].name if frames else None,
                    function_depth=len(frames),
                    argument_index=frames[-1].argument_index if frames else None,
                )
            )
        elif token.type == Token.OPERAND and token.subtype == Token.RANGE:
            resolved = (
                workbook.resolve_name(token.value, sheet_index=sheet_index)
                if workbook is not None
                else None
            )
            range_tokens.append(
                RangeToken(
                    text=token.value,
                    function=frames[-1].name if frames else None,
                    function_depth=len(frames),
                    argument_index=frames[-1].argument_index if frames else None,
                    defined_name=resolved.name if resolved is not None else None,
                )
            )
        previous = token

    return TokenWalk(
        formula=formula,
        numeric_literals=tuple(numeric_literals),
        range_tokens=tuple(range_tokens),
        max_function_depth=max_depth,
        function_count=function_count,
    )


def normalize_formula_shape(formula: str, *, row: int, column: int) -> str:
    """Normalize A1 cell references to relative/absolute R1C1-like shapes.

    Structured table references (`Table[Col]`), whole-row/column refs (`A:A`,
    `1:1`), and 3D refs (`Sheet1:Sheet3!A1`) are passed through unchanged.
    Phase 0 does not claim shape equality for those forms.
    """

    def normalize_reference(match: re.Match[str]) -> str:
        ref_row = int(match.group("row"))
        ref_column = column_index_from_string(match.group("col"))
        row_part = f"R{ref_row}" if match.group("rowabs") else f"R[{ref_row - row}]"
        column_part = f"C{ref_column}" if match.group("colabs") else f"C[{ref_column - column}]"
        return f"{row_part}{column_part}"

    pieces: list[str] = []
    for token in Tokenizer(formula).items:
        value = token.value
        if token.type == Token.OPERAND and token.subtype == Token.RANGE:
            sheet_prefix, separator, reference = value.rpartition("!")
            if separator:
                value = f"{sheet_prefix}{separator}{_CELL_REF.sub(normalize_reference, reference)}"
            else:
                value = _CELL_REF.sub(normalize_reference, value)
        pieces.append(value.upper() if token.type != Token.OPERAND else value)
    return "".join(pieces)
