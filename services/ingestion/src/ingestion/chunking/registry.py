from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from .base_chunker import Chunker
from .ast_code_chunker import ASTCodeChunker
from .sliding_window_chunker import SlidingWindowChunker


class ChunkerStrategy(StrEnum):
    SLIDING_WINDOW = "sliding_window"
    AST_CODE = "ast_code"


_REGISTRY: dict[ChunkerStrategy, type[Chunker]] = {
    ChunkerStrategy.SLIDING_WINDOW: SlidingWindowChunker,
    ChunkerStrategy.AST_CODE: ASTCodeChunker,
}


def get_chunker(
    strategy: ChunkerStrategy = ChunkerStrategy.SLIDING_WINDOW,
    *,
    language: str | None = None,
    chunker_config: Mapping[str, Any] | None = None,
) -> Chunker:
    """Instantiate a chunker by strategy name."""
    cls = _REGISTRY.get(strategy)
    if cls is None:
        raise ValueError(f"Unknown chunker strategy: {strategy}")

    kwargs: dict[str, Any] = dict(chunker_config or {})

    if strategy is ChunkerStrategy.AST_CODE:
        kwargs.setdefault("language", language)
        return cls(**kwargs)

    return cls(**kwargs)


def register_chunker(strategy: ChunkerStrategy, cls: type[Chunker]) -> None:
    """Register a new chunker implementation."""
    _REGISTRY[strategy] = cls
