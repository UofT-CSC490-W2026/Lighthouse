from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str


class SearchResult(BaseModel):
    result: str
