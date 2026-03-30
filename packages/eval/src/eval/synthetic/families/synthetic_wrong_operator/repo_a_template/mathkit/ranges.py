from __future__ import annotations


def overlaps(start1: int, end1: int, start2: int, end2: int) -> bool:
    """Return True when closed intervals [start1,end1] and [start2,end2] share a point."""
    return start1 <= end2 and start2 <= end1


def span_length(start: int, end: int) -> int:
    """Return the number of integers in the closed interval [start, end]."""
    if end < start:
        return 0
    return end - start + 1
