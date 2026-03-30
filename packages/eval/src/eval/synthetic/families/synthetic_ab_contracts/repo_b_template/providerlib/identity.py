from __future__ import annotations


def normalize_username(raw: str) -> str:
    """Trim, collapse internal whitespace, and lowercase usernames."""
    collapsed = " ".join(raw.strip().split())
    if not collapsed:
        raise ValueError("username must not be empty")
    return collapsed.lower()


def choose_primary_email(emails: list[str]) -> str:
    """Return the first non-empty email after trimming and lowercasing it."""
    for email in emails:
        cleaned = email.strip().lower()
        if cleaned:
            return cleaned
    raise ValueError("at least one email is required")


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalize tags while preserving first-seen order."""
    seen: set[str] = set()
    normalized_tags: list[str] = []
    for tag in tags:
        cleaned = "-".join(tag.strip().lower().split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized_tags.append(cleaned)
    return normalized_tags
