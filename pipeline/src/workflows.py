"""Temporal workflow definitions for pipeline execution."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

from .activities import (
    clean_activity,
    ingest_activity,
    mental_model_activity,
    store_activity,
    transform_activity,
)
from .contracts import runtime_index_workflow_id, should_reuse_runtime_workflow
from .state import IndexStatus


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
        current_workflow_id = workflow.info().workflow_id
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
            "repo_id": params.repo_id,
            "repo_url": params.repo_url,
            "ref": params.ref,
            "force_reindex": params.force_reindex,
            "workflow_id": current_workflow_id,
            "canonical_workflow_id": canonical_workflow_id,
        }

        await workflow.execute_activity(
            ingest_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=10),
        )
        await workflow.execute_activity(
            clean_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=10),
        )
        await workflow.execute_activity(
            transform_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
        )
        await workflow.execute_activity(
            store_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=10),
        )
        return {
            "status": IndexStatus.READY.value,
            "workflow_id": current_workflow_id,
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
