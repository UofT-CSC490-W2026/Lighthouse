from __future__ import annotations

from datetime import date

from doclib.dates import add_business_days, days_between, format_iso_date
from doclib.numbers import percentage_of


def completion_summary(done: int, total: int) -> str:
    """Return a completion percentage string."""
    return percentage_of(done, total)


def deadline_label(d: date | None) -> str:
    """Return a formatted deadline label."""
    return format_iso_date(d)


def days_until_deadline(today: date, deadline: date) -> int:
    """Return the number of calendar days between today and deadline."""
    return days_between(today, deadline)


def next_review_date(start: date, business_days: int) -> date:
    """Compute the next review date by adding business days."""
    return add_business_days(start, business_days)
