from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

from shared.schemas.search import SearchResult

T = TypeVar("T", bound=BaseModel)


class SearchStrategy(ABC, Generic[T]):
    @abstractmethod
    async def search(self, payload: T) -> SearchResult:
        ...
