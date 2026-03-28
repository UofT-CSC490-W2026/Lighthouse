from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import cast

from embedding import (
    OPENAI_DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
)


class EmbeddingStrategy(StrEnum):
    OPENAI = "openai"


_REGISTRY: dict[EmbeddingStrategy, type[EmbeddingProvider]] = {
    EmbeddingStrategy.OPENAI: OpenAIEmbeddingProvider,
}


def get_embedding_provider(
    strategy: EmbeddingStrategy = EmbeddingStrategy.OPENAI,
    *,
    model: str = OPENAI_DEFAULT_EMBEDDING_MODEL,
    **kwargs,
) -> EmbeddingProvider:
    """Instantiate an embedding provider by strategy name."""
    cls = _REGISTRY.get(strategy)
    if cls is None:
        raise ValueError(f"Unknown embedding strategy: {strategy}")
    factory = cast(Callable[..., EmbeddingProvider], cls)
    return factory(model=model, **kwargs)


def register_embedding_provider(
    strategy: EmbeddingStrategy, cls: type[EmbeddingProvider]
) -> None:
    """Register a new embedding provider implementation."""
    _REGISTRY[strategy] = cls
