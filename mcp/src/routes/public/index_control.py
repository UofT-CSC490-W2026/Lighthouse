from fastapi import APIRouter, Body, HTTPException, Query, status

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


@router.post(
    "/jobs",
    response_model=StartIndexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start runtime index job",
)
async def start_index_job(request: StartIndexJobRequest) -> StartIndexJobResponse:
    try:
        return await index_control_service.start_job(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Index control backend unavailable",
        ) from exc


@router.get(
    "/jobs/{job_id}",
    response_model=IndexJobStatusResponse,
    summary="Get runtime index job status",
)
async def get_index_job(job_id: str) -> IndexJobStatusResponse:
    try:
        return await index_control_service.get_job(job_id)
    except IndexJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Index job not found: {job_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Index control backend unavailable",
        ) from exc


@router.get(
    "/repos/{repo_id:path}/state",
    response_model=RepoIndexStateResponse,
    summary="Get runtime index readiness for a repository/ref",
)
async def get_repo_index_state(
    repo_id: str,
    ref: str = Query(default="main"),
) -> RepoIndexStateResponse:
    try:
        return await index_control_service.get_repo_state(repo_id=repo_id, ref=ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Index control backend unavailable",
        ) from exc


@router.post(
    "/repos/{repo_id:path}/retry",
    response_model=StartIndexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force retry runtime indexing for a repository/ref",
)
async def retry_repo_index(
    repo_id: str,
    ref: str = Query(default="main"),
    request: RetryIndexJobRequest = Body(default_factory=RetryIndexJobRequest),
) -> StartIndexJobResponse:
    try:
        return await index_control_service.retry_job(
            repo_id=repo_id,
            ref=ref,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Index control backend unavailable",
        ) from exc
