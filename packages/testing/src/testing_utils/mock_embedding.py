from __future__ import annotations

import hashlib
import math

from embedding import EmbeddingProvider

DEFAULT_TEST_DIMENSION = 8


class MockEmbeddingProvider(EmbeddingProvider):
    """Returns deterministic vectors based on text hash. No external API calls."""

    def __init__(self, dimension: int = DEFAULT_TEST_DIMENSION, **kwargs) -> None:
        self.dimension = dimension
        self.call_count = 0
        self.last_texts: list[str] = []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        self.last_texts = texts
        return [self._deterministic_vector(t, self.dimension) for t in texts]

    @staticmethod
    def _deterministic_vector(text: str, dim: int = DEFAULT_TEST_DIMENSION) -> list[float]:
        """SHA256 hash -> first `dim` bytes -> normalize to unit vector."""
        h = hashlib.sha256(text.encode()).digest()
        raw = [float(b) / 255.0 for b in h[:dim]]
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw] if norm > 0 else raw
