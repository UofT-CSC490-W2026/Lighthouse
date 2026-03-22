from .search_strategy import SearchStrategy


class PlaceholderStrategy(SearchStrategy):
    async def search(self, query: str) -> str:
        return query
