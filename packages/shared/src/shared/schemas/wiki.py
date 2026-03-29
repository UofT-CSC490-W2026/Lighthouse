from __future__ import annotations

from pydantic import BaseModel, Field


class WikiStructurePage(BaseModel):
    """A page definition in the wiki outline."""

    title: str
    slug: str
    description: str
    source_file_hints: list[str] = Field(default_factory=list)


class WikiStructureSection(BaseModel):
    """A section in the wiki outline."""

    title: str
    slug: str
    pages: list[WikiStructurePage] = Field(default_factory=list)
    subsections: list[WikiStructureSection] = Field(default_factory=list)


class WikiStructure(BaseModel):
    """Complete wiki outline produced by the LLM."""

    title: str
    description: str
    sections: list[WikiStructureSection]


class GenerateWikiRequest(BaseModel):
    """Request payload for wiki generation."""

    github_repo_id: int
    branch: str = "main"


class GenerateWikiAcceptedResponse(BaseModel):
    """Response payload when wiki generation is accepted."""

    status: str = "accepted"
    workflow_id: str


class WikiPageResponse(BaseModel):
    """A single wiki page in API responses."""

    slug: str
    title: str
    content: str
    section_path: str
    source_files: list[str] = Field(default_factory=list)
    related_pages: list[str] = Field(default_factory=list)


class WikiStatusResponse(BaseModel):
    """Response payload for wiki generation status."""

    github_repo_id: int
    branch: str
    status: str
    wiki_title: str | None = None
    page_count: int = 0


class WikiResponse(BaseModel):
    """Full wiki for a repository."""

    repository_name: str
    branch: str
    title: str
    description: str
    pages: list[WikiPageResponse]
