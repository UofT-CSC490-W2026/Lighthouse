from __future__ import annotations

from enum import StrEnum

from embedding import EmbeddingProvider, OpenAIEmbeddingProvider


class EmbeddingStrategy(StrEnum):
    OPENAI = "openai"


_REGISTRY: dict[EmbeddingStrategy, type[EmbeddingProvider]] = {
    EmbeddingStrategy.OPENAI: OpenAIEmbeddingProvider,
}


def get_embedding_provider(
    strategy: EmbeddingStrategy = EmbeddingStrategy.OPENAI,
    **kwargs,
) -> EmbeddingProvider:
    """Instantiate an embedding provider by strategy name."""
    cls = _REGISTRY.get(strategy)
    if cls is None:
        raise ValueError(f"Unknown embedding strategy: {strategy}")
    return cls(**kwargs)


def register_embedding_provider(
    strategy: EmbeddingStrategy, cls: type[EmbeddingProvider]
) -> None:
    """Register a new embedding provider implementation."""
    _REGISTRY[strategy] = cls


__all__ = [
    "EmbeddingStrategy",
    "get_embedding_provider",
    "register_embedding_provider",
]
