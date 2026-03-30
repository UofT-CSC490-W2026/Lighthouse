from __future__ import annotations

from mathkit.strings import count_words, truncate


def test_count_words_simple() -> None:
    assert count_words("hello world") == 2


def test_count_words_multiple_spaces() -> None:
    assert count_words("one  two  three") == 3


def test_count_words_empty() -> None:
    assert count_words("") == 0


def test_truncate_short() -> None:
    assert truncate("hi", 10) == "hi"


def test_truncate_exact() -> None:
    assert truncate("hello world", 11) == "hello world"


def test_truncate_long() -> None:
    assert truncate("hello world", 8) == "hello..."
