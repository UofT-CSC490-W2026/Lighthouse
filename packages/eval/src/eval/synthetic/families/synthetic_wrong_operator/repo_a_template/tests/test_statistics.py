from __future__ import annotations

import pytest

from mathkit.statistics import mean, median


def test_mean_integers() -> None:
    assert mean([2, 4, 6]) == 4.0


def test_mean_fractional() -> None:
    assert mean([1, 2]) == 1.5


def test_mean_empty_raises() -> None:
    with pytest.raises(ValueError):
        mean([])


def test_median_odd() -> None:
    assert median([3, 1, 2]) == 2


def test_median_even() -> None:
    assert median([1, 2, 3, 4]) == 2.5


def test_median_empty_raises() -> None:
    with pytest.raises(ValueError):
        median([])
