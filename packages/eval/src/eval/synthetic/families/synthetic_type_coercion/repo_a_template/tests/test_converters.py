from __future__ import annotations

from transforms.converters import celsius_to_fahrenheit, kg_to_pounds


def test_celsius_to_fahrenheit_freezing() -> None:
    assert celsius_to_fahrenheit(0) == 32.0


def test_celsius_to_fahrenheit_boiling() -> None:
    assert celsius_to_fahrenheit(100) == 212.0


def test_celsius_to_fahrenheit_body() -> None:
    assert abs(celsius_to_fahrenheit(37) - 98.6) < 0.01


def test_kg_to_pounds_one_kg() -> None:
    assert abs(kg_to_pounds(1) - 2.20462) < 0.001


def test_kg_to_pounds_zero() -> None:
    assert kg_to_pounds(0) == 0.0


def test_kg_to_pounds_ten() -> None:
    assert abs(kg_to_pounds(10) - 22.0462) < 0.001
