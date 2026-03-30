from __future__ import annotations


def safe_subtract(a: float, b: float) -> float:
    """Return a minus b."""
    return a - b


def integer_divide(a: int, b: int) -> int:
    """Return the integer quotient of a divided by b, or zero when b is zero."""
    if b == 0:
        return 0
    return a // b
