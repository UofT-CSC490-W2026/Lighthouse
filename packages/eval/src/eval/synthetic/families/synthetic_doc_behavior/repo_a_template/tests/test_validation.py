from __future__ import annotations

import math

from consumer_app.validation import bounded_progress, compute_score_ratio


def test_compute_score_ratio_normal() -> None:
    assert compute_score_ratio(3, 4) == 0.75


def test_compute_score_ratio_zero_max() -> None:
    assert compute_score_ratio(5, 0) == 0.0


def test_compute_score_ratio_nan_numerator() -> None:
    assert compute_score_ratio(float("nan"), 10) == 0.0


def test_bounded_progress_within_range() -> None:
    assert bounded_progress(50.0) == 50.0


def test_bounded_progress_below() -> None:
    assert bounded_progress(-10.0) == 0.0


def test_bounded_progress_above() -> None:
    assert bounded_progress(200.0) == 100.0


def test_bounded_progress_nan() -> None:
    assert bounded_progress(float("nan")) == 0.0


def test_bounded_progress_swapped_bounds() -> None:
    from doclib.numbers import clamp_to_range
    assert clamp_to_range(5, 10, 0) == 5.0
