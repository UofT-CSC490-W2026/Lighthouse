from __future__ import annotations

from datetime import date, timedelta


def add_business_days(start: date, days: int) -> date:
    """Add *days* business days (Mon-Fri) to *start*.

    Behavior:
    - Adding zero business days returns *start* unchanged — even if *start*
      falls on a weekend.
    - Negative *days* values subtract business days (moving backward).
    - Weekends (Saturday and Sunday) are skipped but the start date itself is
      NOT adjusted when it falls on a weekend.
    """
    if days == 0:
        return start
    direction = 1 if days > 0 else -1
    remaining = abs(days)
    current = start
    while remaining > 0:
        current += timedelta(days=direction)
        if current.weekday() < 5:
            remaining -= 1
    return current


def format_iso_date(d: date | None) -> str:
    """Format a date as an ISO-8601 string.

    Behavior:
    - Returns ``"unknown"`` when *d* is ``None`` — NOT an empty string.
    - The format is always ``YYYY-MM-DD`` with zero-padded month and day.
    """
    if d is None:
        return "unknown"
    return d.isoformat()


def days_between(start: date, end: date) -> int:
    """Return the number of calendar days from *start* to *end*.

    Behavior:
    - The result is always non-negative: if *end* < *start*, the function
      returns the absolute value of the difference.
    - Same-day inputs return 0.
    """
    return abs((end - start).days)
