from __future__ import annotations

from enum import StrEnum

from llm import BedrockLLMProvider, LLMProvider, OpenAILLMProvider


class LLMStrategy(StrEnum):
    BEDROCK = "bedrock"
    OPENAI = "openai"


_REGISTRY: dict[LLMStrategy, type[LLMProvider]] = {
    LLMStrategy.BEDROCK: BedrockLLMProvider,
    LLMStrategy.OPENAI: OpenAILLMProvider,
}


def get_llm_provider(
    strategy: LLMStrategy = LLMStrategy.OPENAI,
    **kwargs,
) -> LLMProvider:
    """Instantiate an LLM provider by strategy name."""
    cls = _REGISTRY.get(strategy)
    if cls is None:
        raise ValueError(f"Unknown LLM strategy: {strategy}")
    return cls(**kwargs)


def register_llm_provider(strategy: LLMStrategy, cls: type[LLMProvider]) -> None:
    """Register a new LLM provider implementation."""
    _REGISTRY[strategy] = cls
