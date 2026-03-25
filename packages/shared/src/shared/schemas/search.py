from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request payload for the search service."""

    query: str
    github_repo_id: int
    branch: str = Field(default="main", min_length=1)
    file_path: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)


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
