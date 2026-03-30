from __future__ import annotations

from providerlib.math_utils import safe_divide


def ratio_or_label(numerator: float, denominator: float, default: str = "n/a") -> str:
    result = safe_divide(numerator, denominator, default=None)
    if result is None:
        return default
    return f"{result:.2f}"
