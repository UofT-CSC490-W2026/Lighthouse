from abc import ABC, abstractmethod


class SearchStrategy(ABC):
    @abstractmethod
    async def search(self, query: str) -> str:
        pass
