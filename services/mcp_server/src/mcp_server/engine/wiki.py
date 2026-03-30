from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

import httpx
from fastapi import Body, Path, Query
from pydantic import BaseModel, Field, ValidationError
from shared.schemas.search import WikiSearchRequest, WikiSearchResult
from shared.schemas.wiki import GenerateWikiRequest

from db import Repository, WikiGeneration, WikiPage

from ..utilities import AuthenticatedUser, RequestError, get_logger, httproute, toolcall

if TYPE_CHECKING:
    from .engine import Engine


class WikiEngine:
    """Expose wiki generation and retrieval entrypoints for agents."""

    log: logging.Logger

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.log = get_logger(__name__)

    @httproute(
        "POST",
        "/v1/wiki/generate",
        name="generate_wiki",
        description="Generate wiki documentation for an indexed repository.",
    )
    async def generate_wiki(
        self,
        auth: AuthenticatedUser,
        repository_name: Annotated[str, Body(...)],
        branch: Annotated[str, Body()] = "main",
    ) -> "GenerateWikiResponse":
        """Trigger wiki generation by calling the ingestion service."""
        normalized_repo_name = repository_name.strip().lower()
        github_repo_id = await asyncio.to_thread(
            self._resolve_github_repo_id, normalized_repo_name
        )
        if github_repo_id is None:
            raise RequestError(
                f"Repository '{normalized_repo_name}' not found.", status_code=404
            )

        ingestion_url = self.engine.app.settings.ingestion_service_url
        request = GenerateWikiRequest(
            github_repo_id=github_repo_id,
            branch=branch.strip() or "main",
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{ingestion_url}/generate-wiki",
                    json=request.model_dump(),
                )
                resp.raise_for_status()
                data = resp.json()
                return GenerateWikiResponse(
                    status="accepted",
                    message=f"Wiki generation started for {normalized_repo_name}/{branch}.",
                    workflow_id=data.get("workflow_id", ""),
                )
        except httpx.HTTPStatusError as exc:
            self.log.error(
                "Ingestion service returned %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise RequestError(
                f"Failed to start wiki generation: {exc.response.status_code}",
                status_code=502,
            ) from exc
        except httpx.RequestError as exc:
            self.log.error("Failed to reach ingestion service: %s", exc)
            raise RequestError(
                "Ingestion service unavailable.", status_code=502
            ) from exc

    @httproute(
        "GET",
        "/v1/wiki/{repository_name:path}",
        name="get_wiki",
        description="Retrieve generated wiki pages for a repository.",
    )
    @toolcall(
        "get_wiki",
        description="Retrieve generated wiki pages for a repository.",
    )
    async def get_wiki(
        self,
        auth: AuthenticatedUser,
        repository_name: Annotated[str, Path(...)],
        branch: Annotated[str, Query()] = "main",
    ) -> "GetWikiResponse":
        """Fetch wiki pages from the database."""
        normalized_repo_name = repository_name.strip().lower()
        result = await asyncio.to_thread(
            self._get_wiki_sync, normalized_repo_name, branch.strip() or "main"
        )
        return result

    @httproute(
        "POST",
        "/v1/wiki/search",
        name="search_wiki",
        description="Search generated wiki documentation.",
    )
    @toolcall(
        "search_wiki",
        description="Search generated wiki documentation.",
    )
    async def search_wiki(
        self,
        auth: AuthenticatedUser,
        repository_name: Annotated[str, Body(...)],
        query: Annotated[str, Body(...)],
        branch: Annotated[str, Body()] = "main",
        top_k: Annotated[int, Body()] = 5,
    ) -> "SearchWikiResponse":
        """Search wiki pages by calling the search service."""
        normalized_repo_name = repository_name.strip().lower()
        github_repo_id = await asyncio.to_thread(
            self._resolve_github_repo_id, normalized_repo_name
        )
        if github_repo_id is None:
            raise RequestError(
                f"Repository '{normalized_repo_name}' not found.", status_code=404
            )

        try:
            search_request = WikiSearchRequest(
                query=query.strip(),
                github_repo_id=github_repo_id,
                branch=branch.strip() or "main",
                top_k=top_k,
            )
        except ValidationError as exc:
            raise RequestError(str(exc), status_code=422) from exc

        search_url = self.engine.app.settings.search_service_url

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{search_url}/search",
                    json=search_request.model_dump(),
                )
                resp.raise_for_status()
                result = WikiSearchResult.model_validate(resp.json())

                return SearchWikiResponse(
                    status="ok",
                    message="Wiki search completed.",
                    snippets=[
                        WikiSnippetResponse(
                            page_title=s.page_title,
                            slug=s.slug,
                            section_path=s.section_path,
                            content_snippet=s.content_snippet,
                            score=s.score,
                        )
                        for s in result.snippets
                    ],
                )
        except httpx.HTTPStatusError as exc:
            self.log.error(
                "Search service returned %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return SearchWikiResponse(
                status="error",
                message=f"Search service error: {exc.response.status_code}",
                snippets=[],
            )
        except httpx.RequestError as exc:
            self.log.error("Failed to reach search service: %s", exc)
            return SearchWikiResponse(
                status="error",
                message="Search service unavailable.",
                snippets=[],
            )

    def _resolve_github_repo_id(self, full_name: str) -> int | None:
        with self.engine.app.database.connection_context():
            repo = Repository.get_or_none(Repository.full_name == full_name)
            if repo is not None:
                return repo.github_repo_id
            return None

    def _get_wiki_sync(self, full_name: str, branch: str) -> "GetWikiResponse":
        with self.engine.app.database.connection_context():
            repo = Repository.get_or_none(Repository.full_name == full_name)
            if repo is None:
                raise RequestError(f"Repository '{full_name}' not found.", status_code=404)

            generation = (
                WikiGeneration.select()
                .where(
                    (WikiGeneration.repository == repo)
                    & (WikiGeneration.branch == branch)
                    & (WikiGeneration.status == "completed")
                )
                .order_by(WikiGeneration.created_at.desc())
                .first()
            )

            if generation is None:
                raise RequestError(
                    f"No completed wiki found for {full_name}/{branch}.",
                    status_code=404,
                )

            pages = list(
                WikiPage.select()
                .where(WikiPage.wiki_generation == generation)
                .order_by(WikiPage.section_path, WikiPage.slug)
            )

            return GetWikiResponse(
                status="ok",
                repository_name=full_name,
                branch=branch,
                wiki_title=generation.wiki_title or full_name,
                wiki_description=generation.wiki_description or "",
                pages=[
                    WikiPageSummary(
                        slug=p.slug,
                        title=p.title,
                        content=p.content,
                        section_path=p.section_path,
                    )
                    for p in pages
                ],
            )


# --- Response Models ---


class GenerateWikiResponse(BaseModel):
    status: str
    message: str
    workflow_id: str = ""


class WikiPageSummary(BaseModel):
    slug: str
    title: str
    content: str
    section_path: str


class GetWikiResponse(BaseModel):
    status: str
    repository_name: str
    branch: str
    wiki_title: str
    wiki_description: str
    pages: list[WikiPageSummary] = Field(default_factory=list)


class WikiSnippetResponse(BaseModel):
    page_title: str
    slug: str
    section_path: str
    content_snippet: str
    score: float = 0.0


class SearchWikiResponse(BaseModel):
    status: str
    message: str
    snippets: list[WikiSnippetResponse] = Field(default_factory=list)
