from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

RequestT = TypeVar("RequestT", bound=BaseModel)
ResultT = TypeVar("ResultT", bound=BaseModel)


class SearchStrategy(ABC, Generic[RequestT, ResultT]):
    @abstractmethod
    async def search(self, request: RequestT) -> ResultT:
        ...
