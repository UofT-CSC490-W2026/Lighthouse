from abc import ABC, abstractmethod

from shared.schemas.search import SearchRequest, SearchResult


class SearchStrategy(ABC):
    @abstractmethod
    async def search(self, request: SearchRequest) -> SearchResult:
        ...
