from __future__ import annotations

from consumer_app.formatting import article_slug, author_display, preview_text


def test_article_slug_simple() -> None:
    assert article_slug("Hello World") == "hello-world"


def test_article_slug_special_chars() -> None:
    assert article_slug("Price: $100!") == "price-100"


def test_article_slug_empty() -> None:
    assert article_slug("   ") == ""


def test_article_slug_leading_trailing_symbols() -> None:
    assert article_slug("--hello--") == "hello"


def test_preview_text_short() -> None:
    assert preview_text("one two three", max_words=5) == "one two three"


def test_preview_text_truncated() -> None:
    assert preview_text("a b c d e f", max_words=3) == "a b c..."


def test_preview_text_zero_words() -> None:
    assert preview_text("hello world", max_words=0) == "..."


def test_author_display_both() -> None:
    assert author_display("jane", "doe") == "Jane Doe"


def test_author_display_first_only() -> None:
    assert author_display("jane", "") == "Jane"


def test_author_display_last_only() -> None:
    assert author_display("", "doe") == "Doe"


def test_author_display_both_empty() -> None:
    assert author_display("", "") == "Anonymous"
