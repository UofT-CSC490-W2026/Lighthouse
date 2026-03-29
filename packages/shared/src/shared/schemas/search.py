from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SearchMethod(str, Enum):
    hybrid = "hybrid"


class SearchContextSource(str, Enum):
    code = "code"
    wiki = "wiki"


class SearchRequest(BaseModel):
    query: str
    github_repo_id: int
    branch: str = Field(default="main", min_length=1)
    file_path: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)
    method: SearchMethod | None = None
    context_source: SearchContextSource = SearchContextSource.code


class HybridRequest(SearchRequest):
    method: SearchMethod = SearchMethod.hybrid


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


class WikiSearchRequest(SearchRequest):
    """Request payload for wiki search."""
    context_source: SearchContextSource = SearchContextSource.wiki
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
