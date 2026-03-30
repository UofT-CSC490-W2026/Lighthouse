from __future__ import annotations


def mean(values: list[float]) -> float:
    """Return the arithmetic mean. Raise ValueError when the list is empty."""
    if not values:
        raise ValueError("Cannot compute mean of empty list")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    """Return the median value. Raise ValueError when the list is empty."""
    if not values:
        raise ValueError("Cannot compute median of empty list")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 0:
        return (ordered[mid - 1] + ordered[mid]) / 2
    return ordered[mid]
