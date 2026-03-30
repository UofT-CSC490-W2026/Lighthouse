from __future__ import annotations

import pytest

from transforms.validators import validate_non_empty, validate_percentage


def test_validate_percentage_integer() -> None:
    assert validate_percentage(50) == 50.0


def test_validate_percentage_float() -> None:
    assert validate_percentage(33.3) == 33.3


def test_validate_percentage_out_of_range() -> None:
    with pytest.raises(ValueError):
        validate_percentage(101)


def test_validate_non_empty_valid() -> None:
    assert validate_non_empty("hello") == "hello"


def test_validate_non_empty_strips() -> None:
    assert validate_non_empty("  hello  ") == "hello"


def test_validate_non_empty_whitespace_only() -> None:
    with pytest.raises(ValueError):
        validate_non_empty("   ")
