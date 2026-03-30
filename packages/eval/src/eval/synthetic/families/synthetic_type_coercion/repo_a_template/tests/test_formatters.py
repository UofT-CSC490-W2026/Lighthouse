from __future__ import annotations

from transforms.formatters import format_bytes, format_percentage


def test_format_percentage_half() -> None:
    assert format_percentage(0.5) == "50.0%"


def test_format_percentage_full() -> None:
    assert format_percentage(1.0) == "100.0%"


def test_format_percentage_zero_decimals() -> None:
    assert format_percentage(0.755, decimals=0) == "76%"


def test_format_bytes_small() -> None:
    assert format_bytes(500) == "500 B"


def test_format_bytes_kilobytes() -> None:
    assert format_bytes(1536) == "1.5 KB"


def test_format_bytes_megabytes() -> None:
    assert format_bytes(2621440) == "2.5 MB"
