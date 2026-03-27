from __future__ import annotations

from enum import StrEnum

from .base_provider import EmbeddingProvider
from .bedrock_provider import BedrockEmbeddingProvider
from .openai_provider import OpenAIEmbeddingProvider


class EmbeddingStrategy(StrEnum):
    BEDROCK = "bedrock"
    OPENAI = "openai"


_REGISTRY: dict[EmbeddingStrategy, type[EmbeddingProvider]] = {
    EmbeddingStrategy.BEDROCK: BedrockEmbeddingProvider,
    EmbeddingStrategy.OPENAI: OpenAIEmbeddingProvider,
}


def get_embedding_provider(
    strategy: EmbeddingStrategy = EmbeddingStrategy.BEDROCK,
    **kwargs,
) -> EmbeddingProvider:
    """Instantiate an embedding provider by strategy name."""
    cls = _REGISTRY.get(strategy)
    if cls is None:
        raise ValueError(f"Unknown embedding strategy: {strategy}")
    return cls(**kwargs)


def register_embedding_provider(
    strategy: EmbeddingStrategy,
    cls: type[EmbeddingProvider],
) -> None:
    """Register a new embedding provider implementation."""
    _REGISTRY[strategy] = cls
