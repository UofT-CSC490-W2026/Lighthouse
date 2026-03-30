from __future__ import annotations


def slugify(text: str) -> str:
    """Convert a string to a URL-friendly slug.

    Behavior:
    - Strips leading and trailing whitespace.
    - Converts the entire string to lowercase.
    - Replaces one or more consecutive non-alphanumeric characters with a single hyphen.
    - Removes any leading or trailing hyphens produced by the replacement step.
    - Returns an empty string when the input is empty or whitespace-only.
    """
    import re

    cleaned = text.strip().lower()
    if not cleaned:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", cleaned)
    return slug.strip("-")


def truncate_words(text: str, max_words: int, *, suffix: str = "...") -> str:
    """Truncate text to at most *max_words* whitespace-separated words.

    Behavior:
    - When *max_words* is less than 1, returns the suffix alone (not an empty string).
    - When the text has fewer than or equal to *max_words* words, returns it unchanged
      (no suffix is appended).
    - Leading and trailing whitespace is preserved on the returned text only when the
      text is NOT truncated.  When truncated, trailing whitespace is removed before
      appending the suffix.
    - The suffix is appended with no separator (directly after the last kept word).
    """
    words = text.split()
    if max_words < 1:
        return suffix
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + suffix


def normalize_name(first: str, last: str) -> str:
    """Return a normalized display name from first and last name parts.

    Behavior:
    - Both parts are stripped of leading/trailing whitespace before processing.
    - Each part is title-cased independently (``str.title()``).
    - The two parts are joined with a single space.
    - If either part is empty after stripping, only the non-empty part is returned.
    - If BOTH parts are empty after stripping, returns the string ``"Anonymous"``.
    """
    f = first.strip().title()
    l = last.strip().title()
    if f and l:
        return f"{f} {l}"
    if f:
        return f
    if l:
        return l
    return "Anonymous"
