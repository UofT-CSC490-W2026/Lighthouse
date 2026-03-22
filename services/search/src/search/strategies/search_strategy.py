from abc import ABC, abstractmethod


class SearchStrategy(ABC):
    @abstractmethod
    async def search(self, query: str) -> str:
        pass


def get_search_strategy() -> SearchStrategy:
    from search.strategies.placeholder_strategy import PlaceholderStrategy
    return PlaceholderStrategy()
