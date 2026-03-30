from __future__ import annotations


def count_words(text: str) -> int:
    """Return the number of whitespace-separated words."""
    if not text.strip():
        return 0
    return len(text.split())


def truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """Shorten text to at most max_length characters, appending suffix when truncated."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
