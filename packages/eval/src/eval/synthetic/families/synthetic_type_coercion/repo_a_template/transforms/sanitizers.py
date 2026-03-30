from __future__ import annotations


def normalize_whitespace(text: str) -> str:
    """Replace consecutive whitespace with a single space and strip edges."""
    return " ".join(text.split())


def truncate_decimal(value: float, places: int) -> float:
    """Truncate (not round) a float to the given number of decimal places."""
    factor = 10 ** places
    return int(value * factor) / factor
