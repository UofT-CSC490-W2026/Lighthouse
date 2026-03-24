from __future__ import annotations

from shared.schemas.search import SearchRequest, SearchResult

from .search_strategy import SearchStrategy


class ExampleStrategy(SearchStrategy):
    async def search(self, request: SearchRequest) -> SearchResult:
        return SearchResult(
            snippets=[],
            query=request.query,
            total_results=0,
        )
