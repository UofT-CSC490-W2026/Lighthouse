from __future__ import annotations


def safe_divide(
    numerator: float,
    denominator: float,
    *,
    default: float | int | None = None,
) -> float | int | None:
    """Divide safely and return *default* when the denominator is zero."""
    if denominator == 0:
        return default
    return numerator / denominator
