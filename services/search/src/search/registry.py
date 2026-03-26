from __future__ import annotations

import asyncio

from shared.schemas.search import CodeSnippet, SearchMethod, SearchRequest, SearchResult
from search.strategies.search_strategy import SearchStrategy


class StrategyRegistry:
    """Maps ``SearchMethod`` enum values to their ``SearchStrategy`` implementations."""

    def __init__(self) -> None:
        self._strategies: dict[SearchMethod, SearchStrategy] = {}

    def register(self, method: SearchMethod, strategy: SearchStrategy) -> None:
        self._strategies[method] = strategy

    def available(self) -> list[str]:
        return [m.value for m in self._strategies]

    async def search(self, requests: list[SearchRequest]) -> SearchResult:
        results = await asyncio.gather(
            *[self._strategies[r.method].search(r) for r in requests]
        )

        if len(results) == 1:
            return results[0]

        top_k = max(r.top_k for r in requests)
        fused = self._rrf_fuse([r.snippets for r in results])
        return SearchResult(
            snippets=fused[:top_k],
            query=requests[0].query,
            total_results=len(fused),
        )

    @staticmethod
    def _rrf_fuse(ranked_lists: list[list[CodeSnippet]], k: int = 60) -> list[CodeSnippet]:
        scores: dict[str, float] = {}
        snippet_map: dict[str, CodeSnippet] = {}

        for ranked in ranked_lists:
            for rank, s in enumerate(ranked):
                key = f"{s.file_path}:{s.start_line}:{s.end_line}"
                scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
                snippet_map.setdefault(key, s)

        return [
            snippet_map[key].model_copy(update={"score": scores[key]})
            for key in sorted(scores, key=lambda x: scores[x], reverse=True)
        ]
