from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class SearchMethod(str, Enum):
    hybrid = "hybrid"


class SearchRequestBase(BaseModel):
    query: str
    github_repo_id: int
    branch: str = Field(default="main", min_length=1)
    file_path: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)


class HybridRequest(SearchRequestBase):
    method: Literal[SearchMethod.hybrid] = SearchMethod.hybrid


SearchRequest = Annotated[
    Union[HybridRequest],
    Field(discriminator="method"),
]


class CodeSnippet(BaseModel):
    """A single code snippet returned by the search service."""

    file_path: str
    start_line: int
    end_line: int
    content: str
    language: str | None = None
    score: float = 0.0
    reason: str | None = None


class SearchResult(BaseModel):
    """Response payload from the search service."""

    snippets: list[CodeSnippet] = Field(default_factory=list)
    query: str
    total_results: int = 0
