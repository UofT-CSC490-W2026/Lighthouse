from __future__ import annotations

from datetime import date

from consumer_app.reporting import (
    completion_summary,
    days_until_deadline,
    deadline_label,
    next_review_date,
)


def test_completion_summary_normal() -> None:
    assert completion_summary(1, 2) == "50.0%"


def test_completion_summary_zero_total() -> None:
    assert completion_summary(5, 0) == "N/A"


def test_completion_summary_negative() -> None:
    assert completion_summary(-1, 4) == "-25.0%"


def test_deadline_label_none() -> None:
    assert deadline_label(None) == "unknown"


def test_deadline_label_date() -> None:
    assert deadline_label(date(2025, 1, 15)) == "2025-01-15"


def test_days_until_deadline_forward() -> None:
    assert days_until_deadline(date(2025, 1, 1), date(2025, 1, 10)) == 9


def test_days_until_deadline_backward() -> None:
    assert days_until_deadline(date(2025, 1, 10), date(2025, 1, 1)) == 9


def test_next_review_date_weekday() -> None:
    assert next_review_date(date(2025, 1, 6), 3) == date(2025, 1, 9)


def test_next_review_date_over_weekend() -> None:
    assert next_review_date(date(2025, 1, 9), 2) == date(2025, 1, 13)


def test_next_review_date_zero_days() -> None:
    assert next_review_date(date(2025, 1, 11), 0) == date(2025, 1, 11)
