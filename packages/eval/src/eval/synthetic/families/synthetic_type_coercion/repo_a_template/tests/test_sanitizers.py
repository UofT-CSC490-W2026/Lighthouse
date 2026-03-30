from __future__ import annotations

from transforms.sanitizers import normalize_whitespace, truncate_decimal


def test_normalize_whitespace_multiple_spaces() -> None:
    assert normalize_whitespace("one  two  three") == "one two three"


def test_normalize_whitespace_tabs() -> None:
    assert normalize_whitespace("one\ttwo\tthree") == "one two three"


def test_normalize_whitespace_strips_edges() -> None:
    assert normalize_whitespace("  hello  ") == "hello"


def test_truncate_decimal_one_place() -> None:
    assert truncate_decimal(3.456, 1) == 3.4


def test_truncate_decimal_two_places() -> None:
    assert truncate_decimal(3.456, 2) == 3.45


def test_truncate_decimal_rounds_down() -> None:
    assert truncate_decimal(3.99, 1) == 3.9
