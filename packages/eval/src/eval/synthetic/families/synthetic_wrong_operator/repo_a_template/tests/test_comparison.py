from __future__ import annotations

from mathkit.comparison import clamp, is_in_range


def test_clamp_within_range() -> None:
    assert clamp(5, 0, 10) == 5


def test_clamp_below_low() -> None:
    assert clamp(-3, 0, 10) == 0


def test_clamp_above_high() -> None:
    assert clamp(15, 0, 10) == 10


def test_is_in_range_inside() -> None:
    assert is_in_range(5, 0, 10) is True


def test_is_in_range_below() -> None:
    assert is_in_range(-1, 0, 10) is False


def test_is_in_range_above() -> None:
    assert is_in_range(11, 0, 10) is False
