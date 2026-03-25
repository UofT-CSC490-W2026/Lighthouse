from __future__ import annotations

import hashlib


def compute_chunk_hash(content: str) -> str:
    """Compute SHA-256 hash of chunk content for dedup."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
