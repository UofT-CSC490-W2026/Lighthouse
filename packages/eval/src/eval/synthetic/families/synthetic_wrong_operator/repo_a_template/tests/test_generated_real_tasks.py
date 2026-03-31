from __future__ import annotations

from mathkit.arithmetic import integer_divide, safe_subtract
from mathkit.comparison import clamp, is_in_range
from mathkit.ranges import overlaps, span_length
from mathkit.statistics import mean, median
from mathkit.strings import count_words, truncate


def test_task_011_safe_subtract_plus() -> None:
    assert safe_subtract(10, 3) == 7

def test_task_012_safe_subtract_multiply() -> None:
    assert safe_subtract(3, 10) == -7

def test_task_013_integer_divide_modulo() -> None:
    assert integer_divide(10, 2) == 5

def test_task_014_integer_divide_negative_floor() -> None:
    assert integer_divide(-7, 2) == -4

def test_task_015_clamp_lower_bound() -> None:
    assert clamp(-3, 0, 10) == 0

def test_task_016_clamp_upper_inclusive() -> None:
    assert clamp(15, 0, 10) == 10

def test_task_017_is_in_range_boolean() -> None:
    assert is_in_range(11, 0, 10) is False

def test_task_018_is_in_range_boundaries() -> None:
    assert is_in_range(0, 0, 10) is True

def test_task_019_overlaps_or() -> None:
    assert overlaps(1, 3, 5, 7) is False

def test_task_020_overlaps_touching() -> None:
    assert overlaps(1, 5, 5, 7) is True

def test_task_021_span_length_off_by_two() -> None:
    assert span_length(1, 5) == 5

def test_task_022_span_length_missing_inclusive() -> None:
    assert span_length(3, 3) == 1

def test_task_023_mean_integer_division() -> None:
    assert mean([1, 2]) == 1.5

def test_task_024_mean_wrong_divisor() -> None:
    assert mean([2, 4, 6]) == 4.0

def test_task_025_median_even_indices() -> None:
    assert median([1, 2, 3, 4]) == 2.5

def test_task_026_median_odd_index() -> None:
    assert median([3, 1, 2]) == 2

def test_task_027_count_words_split_space() -> None:
    assert count_words('one  two  three') == 3

def test_task_028_count_words_empty() -> None:
    assert count_words('') == 0

def test_task_029_truncate_suffix_budget() -> None:
    assert truncate('hello world', 8) == 'hello...'

def test_task_030_truncate_exact_length() -> None:
    assert truncate('hello world', 11) == 'hello world'

