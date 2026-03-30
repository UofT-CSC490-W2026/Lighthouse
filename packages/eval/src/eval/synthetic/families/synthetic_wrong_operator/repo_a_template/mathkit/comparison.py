from __future__ import annotations


def clamp(value: float, low: float, high: float) -> float:
    """Constrain value to the inclusive range [low, high]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def is_in_range(value: float, low: float, high: float) -> bool:
    """Return True when low <= value <= high."""
    return low <= value and value <= high
