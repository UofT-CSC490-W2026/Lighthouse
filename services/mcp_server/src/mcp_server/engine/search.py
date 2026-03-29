from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

import httpx
from fastapi import Body
from pydantic import BaseModel, Field, ValidationError
from shared.schemas.search import HybridRequest, SearchMethod, SearchResult

from db import Repository
from ..utilities import AuthenticatedUser, RequestError, get_logger, httproute, toolcall

if TYPE_CHECKING:
    from .engine import Engine


# Backward-compatible alias used by older tests and callers.
SearchRequest = HybridRequest


class SearchEngine:
    """Expose coding-context retrieval entrypoints for agents."""

    log: logging.Logger

    def __init__(self, engine: Engine) -> None:
        """Bind the search service to the shared engine."""
        self.engine = engine
        self.log = get_logger(__name__)

    @httproute(
        "POST",
        "/v1/search/code-context",
        name="get_code_context",
        description="Request relevant code context for a coding task.",
    )
    @toolcall(
        "get_code_context",
        description="Request relevant code context for a coding task.",
    )
    async def get_code_context(
        self,
        auth: AuthenticatedUser,
        repository_name: Annotated[str, Body(...)],
        query: Annotated[str, Body(...)],
        branch: Annotated[str, Body()] = "main",
        file_path: Annotated[str | None, Body()] = None,
    ) -> "CodeContextResponse":
        """Retrieve code context by calling the search service."""
        normalized_query = query.strip()
        normalized_file_path = file_path.strip() if file_path else None

        if not normalized_query:
            raise RequestError("query is required.", status_code=422)

        # Resolve repository name to github_repo_id
        normalized_repo_name = repository_name.strip().lower()
        github_repo_id = await asyncio.to_thread(
            self._resolve_github_repo_id, normalized_repo_name
        )
        if github_repo_id is None:
            raise RequestError(
                f"Repository '{normalized_repo_name}' not found.", status_code=404
            )

        try:
            search_request = SearchRequest(
                query=normalized_query,
                github_repo_id=github_repo_id,
                branch=branch.strip() or "main",
                file_path=normalized_file_path,
                top_k=10,
            )
        except ValidationError as exc:
            raise RequestError(str(exc), status_code=422) from exc

        # Call search service
        search_url = self.engine.app.settings.search_service_url

        snippets: list[CodeContextSnippet] = []
        status = "ok"
        message = "Code context retrieved successfully."

        token = self.engine.app.settings.internal_service_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                resp = await client.post(
                    f"{search_url}/search",
                    json=[search_request.model_dump()],
                )
                resp.raise_for_status()
                result = SearchResult.model_validate(resp.json())

                for s in result.snippets:
                    snippets.append(
                        CodeContextSnippet(
                            file_path=s.file_path,
                            start_line=s.start_line,
                            end_line=s.end_line,
                            content=s.content,
                            reason=s.reason,
                        )
                    )
        except httpx.HTTPStatusError as exc:
            self.log.error("Search service returned %s: %s", exc.response.status_code, exc.response.text)
            status = "error"
            message = f"Search service error: {exc.response.status_code}"
        except httpx.RequestError as exc:
            self.log.error("Failed to reach search service: %s", exc)
            status = "error"
            message = "Search service unavailable."

        return CodeContextResponse(
            status=status,
            message=message,
            repository_name=normalized_repo_name,
            branch=search_request.branch,
            query=normalized_query,
            requested_by_user_id=auth.id,
            snippets=snippets,
            follow_up=[],
        )

    def _resolve_github_repo_id(self, full_name: str) -> int | None:
        """Look up the github_repo_id for a repository by its full_name."""
        with self.engine.app.database.connection_context():
            repo = Repository.get_or_none(Repository.full_name == full_name)
            if repo is not None:
                return repo.github_repo_id
            return None


class CodeContextSnippet(BaseModel):
    """Represent a retrieved snippet that may help with a coding task."""

    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    content: str
    reason: str | None = None


class CodeContextResponse(BaseModel):
    """Return the response shape for code-context requests."""

    status: str = Field(
        default="ok",
        description="Status of the search: ok, error, or not_implemented.",
    )
    message: str
    repository_name: str
    branch: str
    query: str
    requested_by_user_id: str
    snippets: list[CodeContextSnippet]
    follow_up: list[str]
