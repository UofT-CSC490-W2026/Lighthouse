from __future__ import annotations

from logging import Logger
from typing import TYPE_CHECKING, Annotated

from fastapi import Body
from pydantic import BaseModel, Field

from ..utilities import AuthenticatedUser, RequestError, get_logger, httproute, toolcall

if TYPE_CHECKING:
    from .engine import Engine


class SearchService:
    """Expose coding-context retrieval entrypoints for agents."""

    log: Logger

    def __init__(self, engine: Engine) -> None:
        """Bind the search service to the shared engine."""
        self.engine = engine
        self.log = get_logger(__name__)

    @httproute(
        "POST",
        "/v1/search/code-context",
        name="get_code_context",
        description="Placeholder entrypoint for requesting coding-task context.",
    )
    @toolcall(
        "get_code_context",
        description="Placeholder entrypoint for requesting coding-task context.",
    )
    async def get_code_context(
        self,
        auth: AuthenticatedUser,
        repository_name: Annotated[str, Body(...)],
        task_description: Annotated[str, Body(...)],
        branch: Annotated[str, Body()] = "main",
        latest_commit: Annotated[str | None, Body()] = None,
        file_path: Annotated[str | None, Body()] = None,
        start_line: Annotated[int | None, Body()] = None,
        end_line: Annotated[int | None, Body()] = None,
        selected_text: Annotated[str | None, Body()] = None,
        surrounding_context: Annotated[str | None, Body()] = None,
    ) -> "CodeContextResponse":
        """Capture a code-context request envelope for future retrieval work."""
        normalized_repository_name = repository_name.strip()
        normalized_task_description = task_description.strip()
        normalized_branch = branch.strip() or "main"
        normalized_latest_commit = latest_commit.strip() if latest_commit else None
        normalized_file_path = file_path.strip() if file_path else None
        normalized_selected_text = selected_text.strip() if selected_text else None
        normalized_surrounding_context = (
            surrounding_context.strip() if surrounding_context else None
        )

        if not normalized_repository_name:
            raise RequestError("repository_name is required.", status_code=422)
        if not normalized_task_description:
            raise RequestError("task_description is required.", status_code=422)
        if start_line is not None and start_line < 1:
            raise RequestError("start_line must be greater than 0.", status_code=422)
        if end_line is not None and end_line < 1:
            raise RequestError("end_line must be greater than 0.", status_code=422)
        if start_line is None and end_line is not None:
            raise RequestError(
                "start_line is required when end_line is provided.", status_code=422
            )
        if start_line is not None and end_line is not None and end_line < start_line:
            raise RequestError(
                "end_line must be greater than or equal to start_line.", status_code=422
            )

        return CodeContextResponse(
            status="not_implemented",
            message=(
                "Code context retrieval is not implemented yet. "
                "This placeholder captures the request envelope for future search work."
            ),
            repository_name=normalized_repository_name,
            branch=normalized_branch,
            latest_commit=normalized_latest_commit,
            task_description=normalized_task_description,
            requested_by_user_id=auth.id,
            highlight=CodeContextHighlight(
                file_path=normalized_file_path,
                start_line=start_line,
                end_line=end_line,
                selected_text=normalized_selected_text,
                surrounding_context=normalized_surrounding_context,
            ),
            snippets=[],
            follow_up=[],
        )


class CodeContextHighlight(BaseModel):
    """Describe the file region or editor selection that motivated the request."""

    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    selected_text: str | None = None
    surrounding_context: str | None = None


class CodeContextSnippet(BaseModel):
    """Represent a retrieved snippet that may help with a coding task."""

    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    content: str
    reason: str | None = None


class CodeContextResponse(BaseModel):
    """Return the current placeholder response shape for code-context requests."""

    status: str = Field(
        default="not_implemented",
        description="Placeholder status until search-backed retrieval is implemented.",
    )
    message: str
    repository_name: str
    branch: str
    latest_commit: str | None = None
    task_description: str
    requested_by_user_id: str
    highlight: CodeContextHighlight
    snippets: list[CodeContextSnippet]
    follow_up: list[str]
