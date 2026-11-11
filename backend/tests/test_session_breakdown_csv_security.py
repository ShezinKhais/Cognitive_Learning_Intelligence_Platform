"""Cyber 2 regression tests for spreadsheet-safe session CSV values."""

import pytest

from app.services.session_breakdown import _safe


@pytest.mark.parametrize(
    "value",
    [
        "=1+1",
        "+SUM(1,2)",
        "-1+2",
        "@SUM(A1:A2)",
        "  =1+1",
        "\n=1+1",
        "\t=1+1",
        "\r=1+1",
        " \t@SUM(A1:A2)",
    ],
)
def test_formula_like_csv_values_are_prefixed(value: str) -> None:
    assert _safe(value) == "'" + value


@pytest.mark.parametrize(
    "value",
    [
        "Normal student answer",
        "  Normal answer",
        "The answer is = 2",
        "",
        "Student, Example",
    ],
)
def test_ordinary_csv_values_are_preserved(value: str) -> None:
    assert _safe(value) == value
