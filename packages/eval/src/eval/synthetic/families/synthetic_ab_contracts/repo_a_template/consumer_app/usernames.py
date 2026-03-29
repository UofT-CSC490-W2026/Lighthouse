from __future__ import annotations

from providerlib.identity import normalize_username


def canonical_username(raw: str) -> str:
    return normalize_username(raw)
