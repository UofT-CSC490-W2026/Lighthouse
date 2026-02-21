"""Deterministic text embedding helpers for runtime retrieval paths."""

from __future__ import annotations

import hashlib
import math
import re

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_./:-]+")
DEFAULT_VECTOR_DIMENSIONS = 64


def embed_text(
    text: str, *, dimensions: int = DEFAULT_VECTOR_DIMENSIONS
) -> list[float]:
    """Return a deterministic unit vector embedding for the provided text."""
    if dimensions <= 0:
        raise ValueError("dimensions must be a positive integer")

    tokens = _tokenize(text)
    if not tokens:
        return [0.0] * dimensions

    vector = [0.0] * dimensions
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], byteorder="big") % dimensions
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        weight = 1.0 + (digest[3] / 255.0)
        vector[bucket] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        return [0.0] * dimensions

    return [value / norm for value in vector]


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase lexical tokens for embedding hashing."""
    normalized = (text or "").strip().lower()
    if not normalized:
        return []
    return _TOKEN_PATTERN.findall(normalized)
