from __future__ import annotations

from xllib.inspect import normalize_formula_shape, walk_formula


def test_token_walk_exposes_depth_count_arguments_literals_and_ranges() -> None:
    walk = walk_formula("=IF(SUM(A1:A3)=0,ROUND(B1,2),B1*0.85)")

    assert walk.function_count == 3
    assert walk.max_function_depth == 2
    assert [
        (literal.text, literal.function, literal.argument_index)
        for literal in walk.numeric_literals
    ] == [
        ("0", "IF", 0),
        ("2", "ROUND", 1),
        ("0.85", "IF", 2),
    ]
    assert [(token.text, token.function, token.argument_index) for token in walk.range_tokens] == [
        ("A1:A3", "SUM", 0),
        ("B1", "ROUND", 0),
        ("B1", "IF", 2),
    ]


def test_token_walk_records_negative_numeric_literal() -> None:
    walk = walk_formula("=A1*-1")

    assert walk.numeric_literals[0].text == "-1"
    assert walk.numeric_literals[0].value == -1


def test_formula_shape_normalizes_copied_rows_and_flags_different_shape() -> None:
    first = normalize_formula_shape("=D8*$C$4", row=9, column=4)
    copied = normalize_formula_shape("=E9*$C$4", row=10, column=5)
    aggregate = normalize_formula_shape("=SUM(D9:F9)", row=9, column=7)
    quarter_sheet = normalize_formula_shape("=Q1!D8", row=9, column=4)

    assert first == copied
    assert aggregate != first
    assert "Q1!" in quarter_sheet


def test_formula_shape_leaves_structured_whole_and_3d_refs_unchanged() -> None:
    structured = "=SUM(Table1[Amount])"
    whole_column = "=SUM(A:A)"
    whole_row = "=SUM(1:1)"
    three_d = "=SUM(Sheet1:Sheet3!A1)"

    assert "Table1[Amount]" in normalize_formula_shape(structured, row=2, column=2)
    assert "A:A" in normalize_formula_shape(whole_column, row=2, column=2)
    assert "1:1" in normalize_formula_shape(whole_row, row=2, column=2)
    assert "Sheet1:Sheet3!" in normalize_formula_shape(three_d, row=2, column=2)
