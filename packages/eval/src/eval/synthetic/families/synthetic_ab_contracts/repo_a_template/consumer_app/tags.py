from __future__ import annotations

from providerlib.identity import normalize_tags


def normalized_tag_line(tags: list[str]) -> str:
    return ", ".join(normalize_tags(tags))
