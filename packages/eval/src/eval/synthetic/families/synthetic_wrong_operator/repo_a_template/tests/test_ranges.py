from __future__ import annotations

from mathkit.ranges import overlaps, span_length


def test_overlaps_true() -> None:
    assert overlaps(1, 5, 3, 7) is True


def test_overlaps_false() -> None:
    assert overlaps(1, 3, 5, 7) is False


def test_overlaps_touching() -> None:
    assert overlaps(1, 5, 5, 7) is True


def test_span_length_normal() -> None:
    assert span_length(1, 5) == 5


def test_span_length_single() -> None:
    assert span_length(3, 3) == 1


def test_span_length_empty() -> None:
    assert span_length(5, 3) == 0
