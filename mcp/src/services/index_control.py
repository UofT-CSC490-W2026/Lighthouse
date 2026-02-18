"""Index-control service for Temporal workflow orchestration and state reads."""

from __future__ import annotations

from ..clients import TemporalClientWrapper, WorkflowAlreadyExistsError
from ..types import (
    IndexJobStatusResponse,
    IndexStage,
    IndexStatus,
    RetryIndexJobRequest,
    RepoIndexStateResponse,
    StartIndexJobRequest,
    StartIndexJobResponse,
    runtime_index_workflow_id,
)
from .index_repository import IndexRepository


class IndexJobNotFoundError(LookupError):
    pass


class IndexControlService:
    def __init__(
        self,
        *,
        temporal_client: TemporalClientWrapper,
        repository: IndexRepository,
    ) -> None:
        self.temporal_client = temporal_client
        self.repository = repository

    async def start_job(self, request: StartIndexJobRequest) -> StartIndexJobResponse:
        canonical_workflow_id = runtime_index_workflow_id(request.repo_id, request.ref)
        if request.force_reindex:
            started = await self.temporal_client.start_forced_runtime_index_workflow(
                repo_id=request.repo_id,
                repo_url=request.repo_url,
                ref=request.ref,
                base_workflow_id=canonical_workflow_id,
            )
            return StartIndexJobResponse(
                job_id=started.run_id or started.workflow_id,
                workflow_id=started.workflow_id,
                status=IndexStatus.PENDING,
            )

        try:
            started = await self.temporal_client.start_runtime_index_workflow(
                repo_id=request.repo_id,
                repo_url=request.repo_url,
                ref=request.ref,
                workflow_id=canonical_workflow_id,
                force_reindex=False,
            )
            return StartIndexJobResponse(
                job_id=started.run_id or started.workflow_id,
                workflow_id=started.workflow_id,
                status=IndexStatus.PENDING,
            )
        except WorkflowAlreadyExistsError as exc:
            active_job_id = await self.repository.find_active_job_id(request.repo_id, request.ref)
            fallback_job_id = active_job_id or exc.run_id or canonical_workflow_id
            return StartIndexJobResponse(
                job_id=fallback_job_id,
                workflow_id=canonical_workflow_id,
                status=IndexStatus.PENDING,
            )

    async def retry_job(
        self,
        *,
        repo_id: str,
        ref: str,
        request: RetryIndexJobRequest,
    ) -> StartIndexJobResponse:
        repo_url = request.repo_url or f"https://github.com/{repo_id}"
        return await self.start_job(
            StartIndexJobRequest(
                repo_id=repo_id,
                repo_url=repo_url,
                ref=ref,
                trigger=request.trigger,
                requested_by=request.requested_by,
                force_reindex=True,
            )
        )

    async def get_job(self, job_id: str) -> IndexJobStatusResponse:
        record = await self.repository.get_job(job_id)
        if record is None:
            raise IndexJobNotFoundError(job_id)

        stage = IndexStage(record.stage) if record.stage else None
        status = IndexStatus(record.status)
        return IndexJobStatusResponse(
            job_id=record.job_id,
            repo_id=record.repo_id,
            ref=record.ref,
            status=status,
            stage=stage,
            progress_pct=record.progress_pct,
            workflow_id=record.workflow_id,
            error_code=record.error_code,
            error_message=record.error_message,
        )

    async def get_repo_state(self, *, repo_id: str, ref: str) -> RepoIndexStateResponse:
        record = await self.repository.get_repo_state(repo_id, ref)
        if record is None:
            return RepoIndexStateResponse(
                repo_id=repo_id,
                ref=ref,
                status=IndexStatus.NOT_FOUND,
                snapshot_sha=None,
                active_job_id=None,
            )

        return RepoIndexStateResponse(
            repo_id=record.repo_id,
            ref=record.ref,
            status=IndexStatus(record.status),
            snapshot_sha=record.snapshot_sha,
            active_job_id=record.active_job_id,
        )
