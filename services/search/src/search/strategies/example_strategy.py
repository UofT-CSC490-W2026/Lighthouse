from __future__ import annotations

from shared.schemas.search import HybridRequest, SearchResult

from .search_strategy import SearchStrategy


class ExampleStrategy(SearchStrategy[HybridRequest, SearchResult]):
    async def search(self, request: HybridRequest) -> SearchResult:
        return SearchResult(snippets=[], query=request.query, total_results=0)
