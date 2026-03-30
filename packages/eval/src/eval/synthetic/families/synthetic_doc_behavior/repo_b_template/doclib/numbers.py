from __future__ import annotations

import math


def safe_divide(numerator: float, denominator: float, *, default: float = 0.0) -> float:
    """Divide numerator by denominator, returning *default* when division is impossible.

    Behavior:
    - Returns *default* when the denominator is zero.
    - Returns *default* when either operand is NaN.
    - Returns *default* when the result would be infinity (e.g. 1.0 / 0.0 after
      float edge cases).
    - Otherwise returns ``numerator / denominator`` as a plain float.
    """
    if denominator == 0:
        return default
    if math.isnan(numerator) or math.isnan(denominator):
        return default
    result = numerator / denominator
    if math.isinf(result):
        return default
    return result


def clamp_to_range(value: float, low: float, high: float) -> float:
    """Clamp *value* to the closed interval [low, high].

    Behavior:
    - When ``low > high``, the two bounds are swapped silently before clamping.
    - NaN values are returned as ``low`` (after potential swap) — NaN is never a
      valid clamp result.
    - The return type is always ``float``, even when inputs are ``int``.
    """
    if low > high:
        low, high = high, low
    if math.isnan(value):
        return float(low)
    return float(max(low, min(value, high)))


def percentage_of(part: float, whole: float, *, decimals: int = 1) -> str:
    """Format ``part / whole`` as a percentage string.

    Behavior:
    - When *whole* is zero, returns the string ``"N/A"`` (not ``"0.0%"``).
    - The result is rounded to *decimals* decimal places using Python's built-in
      ``round()`` (banker's rounding).
    - A percent sign is appended with no space: ``"45.5%"``.
    - Negative percentages are allowed and formatted normally: ``"-12.3%"``.
    """
    if whole == 0:
        return "N/A"
    pct = round(part / whole * 100, decimals)
    return f"{pct}%"
