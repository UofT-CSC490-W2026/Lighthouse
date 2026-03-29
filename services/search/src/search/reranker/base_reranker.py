from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RankedDocument:
    """Normalized reranking output for a single document."""

    index: int
    relevance_score: float


class BaseReranker(ABC):
    """Abstract base class for search rerankers."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[RankedDocument]:
        """Rank documents by relevance to the query."""
