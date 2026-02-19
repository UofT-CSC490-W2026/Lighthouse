"""Temporal workflow definitions for pipeline execution."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from .activities import (
    clean_activity,
    ingest_activity,
    mental_model_activity,
    persist_runtime_index_failure_activity,
    persist_runtime_index_progress_activity,
    persist_runtime_index_start_activity,
    persist_runtime_index_success_activity,
    store_activity,
    transform_activity,
)
from .contracts import runtime_index_workflow_id, should_reuse_runtime_workflow
from .state import IndexStage, IndexStatus

_PERSIST_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=5,
)

_RUNTIME_INGEST_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=4,
)

_RUNTIME_CLEAN_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=20),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

_RUNTIME_TRANSFORM_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=20),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

_RUNTIME_STORE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=3),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=45),
    maximum_attempts=4,
)

_OFFLINE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

_MENTAL_MODEL_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=3),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=45),
    maximum_attempts=4,
)


@dataclass
class RuntimeIndexParams:
    """Input contract for runtime repository indexing workflow runs."""

    repo_id: str
    repo_url: str
    ref: str = "main"
    force_reindex: bool = False


@dataclass
class OfflineDatasetParams:
    """Input contract for offline dataset processing workflow runs."""

    dataset_name: str
    dataset_version: str | None = None


@dataclass
class MentalModelParams:
    """Input contract for repository mental-model refresh workflow runs."""

    repo_id: str
    from_sha: str | None = None
    to_sha: str | None = None


@workflow.defn
class RuntimeIndexWorkflow:
    """Workflow orchestrating runtime ingest/clean/transform/store stages."""

    @workflow.run
    async def run(self, params: RuntimeIndexParams) -> dict[str, str]:
        """Execute runtime indexing and persist lifecycle state transitions."""
        workflow_info = workflow.info()
        current_workflow_id = workflow_info.workflow_id
        current_run_id = workflow_info.run_id
        canonical_workflow_id = runtime_index_workflow_id(
            params.repo_id,
            params.ref,
        )

        if (
            should_reuse_runtime_workflow(params.force_reindex)
            and current_workflow_id != canonical_workflow_id
        ):
            workflow.logger.warning(
                "Runtime workflow ID does not match canonical idempotent value "
                "(expected=%s actual=%s)",
                canonical_workflow_id,
                current_workflow_id,
            )

        payload: dict[str, str | bool | None] = {
            "job_id": current_run_id,
            "repo_id": params.repo_id,
            "repo_url": params.repo_url,
            "ref": params.ref,
            "force_reindex": params.force_reindex,
            "workflow_id": current_workflow_id,
            "canonical_workflow_id": canonical_workflow_id,
        }

        await workflow.execute_activity(
            persist_runtime_index_start_activity,
            payload,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_PERSIST_RETRY_POLICY,
        )

        current_stage = IndexStage.INGEST
        current_progress = 0
        stage_payload: dict[str, object] = dict(payload)
        try:
            stage_plan = [
                (
                    IndexStage.INGEST,
                    10,
                    ingest_activity,
                    timedelta(minutes=10),
                    _RUNTIME_INGEST_RETRY_POLICY,
                ),
                (
                    IndexStage.CLEAN,
                    35,
                    clean_activity,
                    timedelta(minutes=10),
                    _RUNTIME_CLEAN_RETRY_POLICY,
                ),
                (
                    IndexStage.TRANSFORM,
                    70,
                    transform_activity,
                    timedelta(minutes=20),
                    _RUNTIME_TRANSFORM_RETRY_POLICY,
                ),
                (
                    IndexStage.STORE,
                    90,
                    store_activity,
                    timedelta(minutes=10),
                    _RUNTIME_STORE_RETRY_POLICY,
                ),
            ]

            for (
                stage,
                progress_pct,
                stage_activity,
                timeout,
                retry_policy,
            ) in stage_plan:
                current_stage = stage
                current_progress = progress_pct
                await workflow.execute_activity(
                    persist_runtime_index_progress_activity,
                    {
                        **stage_payload,
                        "stage": stage.value,
                        "progress_pct": progress_pct,
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_PERSIST_RETRY_POLICY,
                )
                stage_payload = await workflow.execute_activity(
                    stage_activity,
                    stage_payload,
                    start_to_close_timeout=timeout,
                    retry_policy=retry_policy,
                )
        except Exception as exc:
            await workflow.execute_activity(
                persist_runtime_index_failure_activity,
                {
                    **stage_payload,
                    "stage": current_stage.value,
                    "progress_pct": current_progress,
                    "error_code": "RUNTIME_INDEX_FAILED",
                    "error_message": str(exc)[:2000],
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_PERSIST_RETRY_POLICY,
            )
            raise

        await workflow.execute_activity(
            persist_runtime_index_success_activity,
            {
                **stage_payload,
                "snapshot_sha": stage_payload.get("snapshot_sha"),
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_PERSIST_RETRY_POLICY,
        )

        return {
            "status": IndexStatus.READY.value,
            "workflow_id": current_workflow_id,
            "job_id": current_run_id,
        }


@workflow.defn
class OfflineDatasetWorkflow:
    """Workflow orchestrating offline dataset processing stages."""

    @workflow.run
    async def run(self, params: OfflineDatasetParams) -> dict[str, str]:
        """Run ingest/clean/transform/store over an offline dataset payload."""
        payload = {
            "dataset_name": params.dataset_name,
            "dataset_version": params.dataset_version,
        }
        await workflow.execute_activity(
            ingest_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=_OFFLINE_RETRY_POLICY,
        )
        await workflow.execute_activity(
            clean_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=_OFFLINE_RETRY_POLICY,
        )
        await workflow.execute_activity(
            transform_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=_OFFLINE_RETRY_POLICY,
        )
        await workflow.execute_activity(
            store_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=_OFFLINE_RETRY_POLICY,
        )
        return {"status": IndexStatus.READY.value}


@workflow.defn
class MentalModelWorkflow:
    """Workflow for computing repository mental-model artifacts."""

    @workflow.run
    async def run(self, params: MentalModelParams) -> dict[str, str]:
        """Execute mental-model activity for a repository commit range."""
        payload = {
            "repo_id": params.repo_id,
            "from_sha": params.from_sha,
            "to_sha": params.to_sha,
        }
        await workflow.execute_activity(
            mental_model_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=_MENTAL_MODEL_RETRY_POLICY,
        )
        return {"status": IndexStatus.READY.value}
