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
        typed_requests: list[tuple[SearchMethod, SearchRequest]] = []
        for request in requests:
            if request.method is None:
                raise ValueError("StrategyRegistry requests must include a search method.")
            typed_requests.append((request.method, request))
        results = await asyncio.gather(
            *[self._strategies[method].search(request) for method, request in typed_requests]
        )

        if len(results) == 1:
            return results[0]

        top_k = max(request.top_k for _, request in typed_requests)
        fused = self._rrf_fuse([r.snippets for r in results])
        return SearchResult(
            snippets=fused[:top_k],
            query=typed_requests[0][1].query,
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
