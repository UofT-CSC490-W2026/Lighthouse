from __future__ import annotations

from shared.schemas.search import HybridRequest, SearchResult

from .search_strategy import SearchStrategy


class ExampleStrategy(SearchStrategy[HybridRequest]):
    async def search(self, payload: HybridRequest) -> SearchResult:
        return SearchResult(snippets=[], query=payload.query, total_results=0)
