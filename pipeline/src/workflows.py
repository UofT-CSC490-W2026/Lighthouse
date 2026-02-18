"""Temporal workflow definitions for pipeline execution."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

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


@dataclass
class RuntimeIndexParams:
    repo_id: str
    repo_url: str
    ref: str = "main"
    force_reindex: bool = False


@dataclass
class OfflineDatasetParams:
    dataset_name: str
    dataset_version: str | None = None


@dataclass
class MentalModelParams:
    repo_id: str
    from_sha: str | None = None
    to_sha: str | None = None


@workflow.defn
class RuntimeIndexWorkflow:
    @workflow.run
    async def run(self, params: RuntimeIndexParams) -> dict[str, str]:
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

        payload = {
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
        )

        current_stage = IndexStage.INGEST
        current_progress = 0
        try:
            stage_plan = [
                (IndexStage.INGEST, 10, ingest_activity, timedelta(minutes=10)),
                (IndexStage.CLEAN, 35, clean_activity, timedelta(minutes=10)),
                (IndexStage.TRANSFORM, 70, transform_activity, timedelta(minutes=20)),
                (IndexStage.STORE, 90, store_activity, timedelta(minutes=10)),
            ]

            for stage, progress_pct, stage_activity, timeout in stage_plan:
                current_stage = stage
                current_progress = progress_pct
                await workflow.execute_activity(
                    persist_runtime_index_progress_activity,
                    {
                        **payload,
                        "stage": stage.value,
                        "progress_pct": progress_pct,
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                )
                await workflow.execute_activity(
                    stage_activity,
                    payload,
                    start_to_close_timeout=timeout,
                )
        except Exception as exc:
            await workflow.execute_activity(
                persist_runtime_index_failure_activity,
                {
                    **payload,
                    "stage": current_stage.value,
                    "progress_pct": current_progress,
                    "error_code": "RUNTIME_INDEX_FAILED",
                    "error_message": str(exc)[:2000],
                },
                start_to_close_timeout=timedelta(seconds=30),
            )
            raise

        await workflow.execute_activity(
            persist_runtime_index_success_activity,
            {
                **payload,
                "snapshot_sha": None,
            },
            start_to_close_timeout=timedelta(seconds=30),
        )

        return {
            "status": IndexStatus.READY.value,
            "workflow_id": current_workflow_id,
            "job_id": current_run_id,
        }


@workflow.defn
class OfflineDatasetWorkflow:
    @workflow.run
    async def run(self, params: OfflineDatasetParams) -> dict[str, str]:
        payload = {
            "dataset_name": params.dataset_name,
            "dataset_version": params.dataset_version,
        }
        await workflow.execute_activity(
            ingest_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=30),
        )
        await workflow.execute_activity(
            clean_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
        )
        await workflow.execute_activity(
            transform_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=30),
        )
        await workflow.execute_activity(
            store_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
        )
        return {"status": IndexStatus.READY.value}


@workflow.defn
class MentalModelWorkflow:
    @workflow.run
    async def run(self, params: MentalModelParams) -> dict[str, str]:
        payload = {
            "repo_id": params.repo_id,
            "from_sha": params.from_sha,
            "to_sha": params.to_sha,
        }
        await workflow.execute_activity(
            mental_model_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
        )
        return {"status": IndexStatus.READY.value}
