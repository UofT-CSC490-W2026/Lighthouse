from __future__ import annotations

import xxhash


def compute_chunk_hash(content: str) -> str:
    """Compute a stable content hash for chunk deduplication."""
    # Deduplication does not require cryptographic guarantees; xxh64 is much faster
    # than SHA-256 while still providing a low collision rate for this use-case.
    return xxhash.xxh64_hexdigest(content)
