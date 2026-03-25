from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts and return their vector representations."""

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text string."""
        return self.embed_batch([text])[0]
