from __future__ import annotations

from mathkit.arithmetic import integer_divide, safe_subtract


def test_safe_subtract_positive() -> None:
    assert safe_subtract(10, 3) == 7


def test_safe_subtract_negative() -> None:
    assert safe_subtract(3, 10) == -7


def test_safe_subtract_zero() -> None:
    assert safe_subtract(5, 5) == 0


def test_integer_divide_exact() -> None:
    assert integer_divide(10, 2) == 5


def test_integer_divide_truncates() -> None:
    assert integer_divide(7, 2) == 3


def test_integer_divide_by_zero() -> None:
    assert integer_divide(5, 0) == 0
