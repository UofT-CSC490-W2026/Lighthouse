from .search_strategy import SearchStrategy


class ExampleStrategy(SearchStrategy):
    async def search(self, query: str) -> str:
        return query
