from __future__ import annotations


def clamp_percentage(value: float | int) -> int:
    """Clamp a numeric percentage to the inclusive range [0, 100]."""
    rounded = int(round(float(value)))
    if rounded < 0:
        return 0
    if rounded > 100:
        return 100
    return rounded


def seconds_to_timeout_ms(seconds: float | int | None) -> int:
    """Convert seconds to milliseconds. Missing values map to zero."""
    if seconds is None:
        return 0
    return max(0, int(round(float(seconds) * 1000)))
