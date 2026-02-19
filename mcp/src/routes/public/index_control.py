"""Public index-control endpoints used by MCP callers and operators."""

from typing import TypeVar

from fastapi import APIRouter, Body, Query, Request, status

from ...auth import extract_request_auth
from ...errors import (
    BackendUnavailableError,
    RequestValidationAppError,
    ResourceNotFoundError,
    WorkflowExecutionError,
)
from ...services import index_control_service
from ...services.index_control import IndexJobNotFoundError
from ...types import (
    IndexJobStatusResponse,
    RepoIndexStateResponse,
    RetryIndexJobRequest,
    StartIndexJobRequest,
    StartIndexJobResponse,
)

router = APIRouter(prefix="/v1/index", tags=["index-control"])

TIndexRequest = TypeVar("TIndexRequest", StartIndexJobRequest, RetryIndexJobRequest)


def _attach_request_github_token(
    request_model: TIndexRequest,
    http_request: Request,
) -> TIndexRequest:
    """Attach optional request-scoped GitHub token when header is present."""
    auth = extract_request_auth(http_request)
    if not auth.github_token:
        return request_model
    if getattr(request_model, "github_token", None):
        return request_model
    return request_model.model_copy(update={"github_token": auth.github_token})


@router.post(
    "/jobs",
    response_model=StartIndexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start runtime index job",
)
async def start_index_job(
    http_request: Request,
    request: StartIndexJobRequest,
) -> StartIndexJobResponse:
    """Start a runtime index workflow for a repository/ref target."""
    try:
        start_request = _attach_request_github_token(request, http_request)
        return await index_control_service.start_job(start_request)
    except ValueError as exc:
        raise RequestValidationAppError(str(exc)) from exc
    except RuntimeError as exc:
        raise BackendUnavailableError("Index control backend unavailable") from exc
    except Exception as exc:
        raise WorkflowExecutionError(
            "Failed to start runtime indexing workflow"
        ) from exc


@router.get(
    "/jobs/{job_id}",
    response_model=IndexJobStatusResponse,
    summary="Get runtime index job status",
)
async def get_index_job(job_id: str) -> IndexJobStatusResponse:
    """Fetch status for a single index job id."""
    try:
        return await index_control_service.get_job(job_id)
    except IndexJobNotFoundError as exc:
        raise ResourceNotFoundError(f"Index job not found: {job_id}") from exc
    except RuntimeError as exc:
        raise BackendUnavailableError("Index control backend unavailable") from exc


@router.get(
    "/repos/{repo_id:path}/state",
    response_model=RepoIndexStateResponse,
    summary="Get runtime index readiness for a repository/ref",
)
async def get_repo_index_state(
    repo_id: str,
    ref: str = Query(default="main"),
) -> RepoIndexStateResponse:
    """Fetch repo-level index readiness state for a specific ref."""
    try:
        return await index_control_service.get_repo_state(repo_id=repo_id, ref=ref)
    except ValueError as exc:
        raise RequestValidationAppError(str(exc)) from exc
    except RuntimeError as exc:
        raise BackendUnavailableError("Index control backend unavailable") from exc


@router.post(
    "/repos/{repo_id:path}/retry",
    response_model=StartIndexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force retry runtime indexing for a repository/ref",
)
async def retry_repo_index(
    http_request: Request,
    repo_id: str,
    ref: str = Query(default="main"),
    request: RetryIndexJobRequest = Body(default_factory=RetryIndexJobRequest),
) -> StartIndexJobResponse:
    """Force-start a retry run for runtime indexing."""
    try:
        retry_request = _attach_request_github_token(request, http_request)
        return await index_control_service.retry_job(
            repo_id=repo_id,
            ref=ref,
            request=retry_request,
        )
    except ValueError as exc:
        raise RequestValidationAppError(str(exc)) from exc
    except RuntimeError as exc:
        raise BackendUnavailableError("Index control backend unavailable") from exc
    except Exception as exc:
        raise WorkflowExecutionError(
            "Failed to retry runtime indexing workflow"
        ) from exc
