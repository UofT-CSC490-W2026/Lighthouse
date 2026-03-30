from __future__ import annotations

from doclib.text import normalize_name, slugify, truncate_words


def article_slug(title: str) -> str:
    """Generate a URL slug for an article title."""
    return slugify(title)


def preview_text(body: str, max_words: int = 20) -> str:
    """Return a preview snippet of the article body."""
    return truncate_words(body, max_words)


def author_display(first: str, last: str) -> str:
    """Return the formatted author display name."""
    return normalize_name(first, last)
