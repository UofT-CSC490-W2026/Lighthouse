from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated, Any, Union

import httpx
from fastapi import Body
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from pydantic import Discriminator, Tag
from shared.schemas.search import CombinedSearchResult, HybridRequest, SearchContextSource, SearchMethod, SearchResult, WikiSearchResult

from db import Repository
from ..utilities import (
    AppError,
    AuthenticatedUser,
    get_logger,
    httproute,
    log_error,
    to_public_error,
    toolcall,
)

if TYPE_CHECKING:
    from .engine import Engine


# Backward-compatible alias used by older tests and callers.
SearchRequest = HybridRequest


def _discriminate_result_type(data: object) -> str:
    """Return the discriminator tag, inferring it when 'type' is absent."""
    if not isinstance(data, dict):
        return "code"
    if "type" in data:
        return data["type"]
    # Fallback for search service responses that predate the type field.
    snippets = data.get("snippets", [])
    if snippets:
        first = snippets[0]
        if "context_source" in first:
            return "combined"
        if "content_snippet" in first:
            return "wiki"
    return "code"


_SearchServiceResult = TypeAdapter(
    Annotated[
        Union[
            Annotated[SearchResult, Tag("code")],
            Annotated[WikiSearchResult, Tag("wiki")],
            Annotated[CombinedSearchResult, Tag("combined")],
        ],
        Discriminator(_discriminate_result_type),
    ]
)


def _extract_snippets(data: dict) -> list["CodeContextSnippet"]:
    """Normalize search service response into CodeContextSnippets."""
    parsed = _SearchServiceResult.validate_python(data)

    if isinstance(parsed, CombinedSearchResult):
        return [
            CodeContextSnippet(
                context_source=s.context_source,
                file_path=s.file_path,
                start_line=s.start_line,
                end_line=s.end_line,
                content=s.content,
                reason=s.reason,
                page_title=s.page_title,
                slug=s.slug,
                section_path=s.section_path,
            )
            for s in parsed.snippets
        ]

    if isinstance(parsed, WikiSearchResult):
        return [
            CodeContextSnippet(
                context_source=SearchContextSource.wiki,
                content=s.content_snippet,
                page_title=s.page_title,
                slug=s.slug,
                section_path=s.section_path,
            )
            for s in parsed.snippets
        ]

    return [
        CodeContextSnippet(
            context_source=SearchContextSource.code,
            file_path=s.file_path,
            start_line=s.start_line,
            end_line=s.end_line,
            content=s.content,
            reason=s.reason,
        )
        for s in parsed.snippets
    ]


class SearchEngine:
    """Expose coding-context retrieval entrypoints for agents."""

    SEARCH_CODE_DESCRIPTION = (
        "Retrieve indexed code/wiki context for a coding task."
        " Use a focused query; start with top_k=5 and keep top_k<=15."
    )

    log: logging.Logger

    def __init__(self, engine: Engine) -> None:
        """Bind the search service to the shared engine."""
        self.engine = engine
        self.log = get_logger(__name__)

    @httproute(
        "POST",
        "/v1/search/search-code",
        name="search_code",
        description=SEARCH_CODE_DESCRIPTION,
    )
    @toolcall(
        "search_code",
        description=SEARCH_CODE_DESCRIPTION,
    )
    async def search_code(
        self,
        auth: AuthenticatedUser,
        repository_name: Annotated[
            str,
            Body(
                ...,
                description="Target repository full name, for example 'owner/repo'.",
            ),
        ],
        query: Annotated[
            str,
            Body(
                ...,
                description=(
                    "Task-focused query. Include symbols, API names, errors, or subsystem terms."
                ),
            ),
        ],
        branch: Annotated[
            str,
            Body(
                description="Repository branch to query. Defaults to 'main'.",
            ),
        ] = "main",
        file_path: Annotated[
            str | None,
            Body(
                description=(
                    "Optional file path scope to narrow retrieval when a specific file is suspected."
                ),
            ),
        ] = None,
        top_k: Annotated[
            int,
            Body(
                ge=1,
                le=15,
                description=(
                    "Maximum snippets to return. Use 5 for typical searches; increase only when scope is broad."
                ),
            ),
        ] = 5,
    ) -> "CodeContextResponse":
        """Retrieve code context by calling the search service."""
        normalized_query = query.strip()
        normalized_file_path = file_path.strip() if file_path else None

        if not normalized_query:
            raise AppError(
                message="query is required.",
                status_code=422,
                error_code="INVALID_ARGUMENT",
                recoverable=True,
                context={"field": "query"},
                internal_message="Empty query after normalization.",
            )

        # Resolve repository name to github_repo_id
        normalized_repo_name = repository_name.strip().lower()
        github_repo_id = await asyncio.to_thread(
            self._resolve_github_repo_id, normalized_repo_name
        )
        if github_repo_id is None:
            raise AppError(
                message=f"Repository '{normalized_repo_name}' not found.",
                status_code=404,
                error_code="REPOSITORY_NOT_FOUND_OR_INACCESSIBLE",
                recoverable=True,
                context={"repository_name": normalized_repo_name},
            )

        try:
            search_request = SearchRequest(
                query=normalized_query,
                github_repo_id=github_repo_id,
                branch=branch.strip() or "main",
                file_path=normalized_file_path,
                top_k=top_k,
                context_sources=(SearchContextSource.code, SearchContextSource.wiki),
            )
        except ValidationError as exc:
            raise AppError(
                message="Invalid search request payload.",
                status_code=422,
                error_code="INVALID_ARGUMENT",
                recoverable=True,
                context={"repository_name": normalized_repo_name},
                internal_message="SearchRequest validation failed.",
                cause_metadata={"validation_error": str(exc)},
            ) from exc

        # Call search service
        search_url = self.engine.app.settings.search_service_url

        snippets: list[CodeContextSnippet] = []
        status = "ok"
        message = "Code context retrieved successfully."
        error_code: str | None = None
        error_id: str | None = None
        recoverable: bool | None = None
        context: dict[str, Any] = {}

        token = self.engine.app.settings.internal_service_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                resp = await client.post(
                    f"{search_url}/search",
                    json=search_request.model_dump(
                        mode="json",
                        exclude_none=True,
                        exclude={"method", "context_source"},
                    ),
                )
                resp.raise_for_status()
                snippets = _extract_snippets(resp.json())
        except httpx.HTTPStatusError as exc:
            app_error = self._map_search_http_error(exc, search_request.branch)
            _, envelope = to_public_error(app_error)
            log_error(self.log, app_error, envelope)
            status = "error"
            message = envelope.message
            error_code = envelope.error_code
            error_id = envelope.error_id
            recoverable = envelope.recoverable
            context = envelope.context
        except httpx.RequestError as exc:
            app_error = AppError(
                message="Search service unavailable.",
                status_code=502,
                error_code="UPSTREAM_UNAVAILABLE",
                recoverable=True,
                context={"service": "search"},
                internal_message=str(exc),
                cause_metadata={"request_url": str(exc.request.url) if exc.request else None},
            )
            _, envelope = to_public_error(app_error)
            log_error(self.log, app_error, envelope)
            status = "error"
            message = envelope.message
            error_code = envelope.error_code
            error_id = envelope.error_id
            recoverable = envelope.recoverable
            context = envelope.context

        return CodeContextResponse(
            status=status,
            message=message,
            error_code=error_code,
            error_id=error_id,
            recoverable=recoverable,
            context=context,
            repository_name=normalized_repo_name,
            branch=search_request.branch,
            query=normalized_query,
            requested_by_user_id=auth.id,
            snippets=snippets,
            follow_up=[],
        )

    def _map_search_http_error(
        self,
        exc: httpx.HTTPStatusError,
        branch: str,
    ) -> AppError:
        """Map search-service HTTP failures to a structured public error."""
        status_code = exc.response.status_code
        response_json: dict[str, Any] | None = None
        try:
            payload = exc.response.json()
            if isinstance(payload, dict):
                response_json = payload
        except ValueError:
            response_json = None

        detail = response_json.get("detail") if response_json else None
        detail_obj = detail if isinstance(detail, dict) else None
        detail_text = detail if isinstance(detail, str) else None
        upstream_code = None
        upstream_message = None
        upstream_context: dict[str, Any] = {}
        if detail_obj is not None:
            upstream_code = detail_obj.get("error_code") or detail_obj.get("code")
            upstream_message = detail_obj.get("message")
            if isinstance(detail_obj.get("context"), dict):
                upstream_context = detail_obj["context"]

        error_code = "UPSTREAM_ERROR"
        message = "Search service returned an error."
        recoverable = False
        context: dict[str, Any] = {
            "service": "search",
            "upstream_status": status_code,
        }
        if upstream_context:
            context["upstream_context"] = upstream_context

        if status_code == 404:
            if upstream_code == "BRANCH_UNAVAILABLE":
                error_code = "BRANCH_UNAVAILABLE"
                message = upstream_message or "Requested branch is not indexed or does not exist."
                recoverable = True
                context["requested_branch"] = upstream_context.get("requested_branch", branch)
                if "indexed_branches" in upstream_context:
                    context["indexed_branches"] = upstream_context["indexed_branches"]
            else:
                error_code = "REPOSITORY_NOT_FOUND_OR_INACCESSIBLE"
                message = upstream_message or "Repository is not available for search."
                recoverable = True
        elif status_code in (502, 503, 504):
            error_code = "UPSTREAM_UNAVAILABLE"
            message = "Search service unavailable."
            recoverable = True
        elif status_code in (400, 422):
            error_code = "INVALID_ARGUMENT"
            message = upstream_message or detail_text or "Invalid search request."
            recoverable = True

        return AppError(
            message=message,
            status_code=502 if status_code >= 500 else status_code,
            error_code=error_code,
            recoverable=recoverable,
            context=context,
            internal_message=f"Search service returned {status_code}.",
            upstream_detail=response_json if response_json is not None else exc.response.text,
            cause_metadata={"upstream_error_code": upstream_code},
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

    context_source: SearchContextSource = SearchContextSource.code
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    content: str
    reason: str | None = None
    page_title: str | None = None
    slug: str | None = None
    section_path: str | None = None


class CodeContextResponse(BaseModel):
    """Return the response shape for search-code requests."""

    status: str = Field(
        default="ok",
        description="Status of the search: ok, error, or not_implemented.",
    )
    message: str
    error_code: str | None = None
    error_id: str | None = None
    recoverable: bool | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    repository_name: str
    branch: str
    query: str
    requested_by_user_id: str
    snippets: list[CodeContextSnippet]
    follow_up: list[str]
