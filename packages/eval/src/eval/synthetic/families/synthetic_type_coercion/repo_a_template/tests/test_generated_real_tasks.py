from __future__ import annotations

import pytest

from transforms.converters import celsius_to_fahrenheit, kg_to_pounds
from transforms.formatters import format_bytes, format_percentage
from transforms.parsers import parse_port, safe_float
from transforms.sanitizers import normalize_whitespace, truncate_decimal
from transforms.validators import validate_non_empty, validate_percentage


def test_task_011_parse_port_strip() -> None:
    assert parse_port('  443  ') == 443

def test_task_012_parse_port_max_bound() -> None:
    assert parse_port('65535') == 65535

def test_task_013_safe_float_decimal() -> None:
    assert safe_float('3.14') == 3.14

def test_task_014_safe_float_negative() -> None:
    assert safe_float('-1.5') == -1.5

def test_task_015_format_percentage_scale() -> None:
    assert format_percentage(0.5) == '50.0%'

def test_task_016_format_percentage_decimals_arg() -> None:
    assert format_percentage(0.755, decimals=0) == '76%'

def test_task_017_format_bytes_kb_precision() -> None:
    assert format_bytes(1536) == '1.5 KB'

def test_task_018_format_bytes_threshold() -> None:
    assert format_bytes(1536) == '1.5 KB'

def test_task_019_celsius_offset() -> None:
    assert celsius_to_fahrenheit(0) == 32.0

def test_task_020_celsius_multiplier() -> None:
    assert celsius_to_fahrenheit(100) == 212.0

def test_task_021_kg_to_pounds_operator() -> None:
    assert abs(kg_to_pounds(10) - 22.0462) < 0.001

def test_task_022_kg_to_pounds_constant() -> None:
    assert abs(kg_to_pounds(1) - 2.20462) < 0.001

def test_task_023_validate_percentage_float() -> None:
    assert validate_percentage(33.3) == 33.3

def test_task_024_validate_percentage_upper_bound() -> None:
    import pytest
    with pytest.raises(ValueError):
        validate_percentage(101)

def test_task_025_validate_non_empty_whitespace() -> None:
    import pytest
    with pytest.raises(ValueError):
        validate_non_empty('   ')

def test_task_026_validate_non_empty_preserve_case() -> None:
    assert validate_non_empty('  Hello  ') == 'Hello'

def test_task_027_normalize_whitespace_tabs() -> None:
    assert normalize_whitespace('one\ttwo\tthree') == 'one two three'

def test_task_028_normalize_whitespace_collapse() -> None:
    assert normalize_whitespace('one  two  three') == 'one two three'

def test_task_029_truncate_decimal_rounding() -> None:
    assert truncate_decimal(3.456, 2) == 3.45

def test_task_030_truncate_decimal_scaling() -> None:
    assert truncate_decimal(3.456, 2) == 3.45

