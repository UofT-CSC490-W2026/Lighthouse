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


class WikiSearchRequest(BaseModel):
    """Request payload for wiki search."""

    query: str
    github_repo_id: int
    branch: str = Field(default="main", min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class WikiSnippet(BaseModel):
    """A single wiki page snippet returned by wiki search."""

    page_title: str
    slug: str
    section_path: str
    content_snippet: str
    score: float = 0.0


class WikiSearchResult(BaseModel):
    """Response payload from wiki search."""

    snippets: list[WikiSnippet] = Field(default_factory=list)
    query: str
    total_results: int = 0
