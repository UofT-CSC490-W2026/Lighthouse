from __future__ import annotations

from enum import StrEnum

from .base_chunker import Chunker
from .chunker import SlidingWindowChunker


class ChunkerStrategy(StrEnum):
    SLIDING_WINDOW = "sliding_window"


_REGISTRY: dict[ChunkerStrategy, type[Chunker]] = {
    ChunkerStrategy.SLIDING_WINDOW: SlidingWindowChunker,
}


def get_chunker(strategy: ChunkerStrategy = ChunkerStrategy.SLIDING_WINDOW) -> Chunker:
    """Instantiate a chunker by strategy name."""
    cls = _REGISTRY.get(strategy)
    if cls is None:
        raise ValueError(f"Unknown chunker strategy: {strategy}")
    return cls()


def register_chunker(strategy: ChunkerStrategy, cls: type[Chunker]) -> None:
    """Register a new chunker implementation."""
    _REGISTRY[strategy] = cls
