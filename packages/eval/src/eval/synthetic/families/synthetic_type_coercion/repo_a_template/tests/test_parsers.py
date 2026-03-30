from __future__ import annotations

import pytest

from transforms.parsers import parse_port, safe_float


def test_parse_port_valid() -> None:
    assert parse_port("80") == 80


def test_parse_port_with_whitespace() -> None:
    assert parse_port("  443  ") == 443


def test_parse_port_out_of_range() -> None:
    with pytest.raises(ValueError):
        parse_port("70000")


def test_safe_float_valid() -> None:
    assert safe_float("3.14") == 3.14


def test_safe_float_invalid() -> None:
    assert safe_float("abc") == 0.0


def test_safe_float_empty() -> None:
    assert safe_float("") == 0.0
