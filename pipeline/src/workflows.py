"""Temporal workflow definitions for pipeline execution."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from temporalio import exceptions as temporal_exceptions
from temporalio import workflow
from temporalio.common import RetryPolicy

from .activities import (
    baseline_evaluation_activity,
    clean_activity,
    evaluation_refresh_activity,
    ingest_activity,
    mental_model_activity,
    persist_runtime_index_failure_activity,
    persist_runtime_index_progress_activity,
    persist_pipeline_run_metrics_activity,
    persist_runtime_index_start_activity,
    persist_runtime_index_success_activity,
    store_activity,
    transform_activity,
)
from .contracts import runtime_index_workflow_id, should_reuse_runtime_workflow
from .observability import structured_event
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

_EVALUATION_REFRESH_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

_FAILURE_CLASS_RETRYABLE = "retryable"
_FAILURE_CLASS_TERMINAL = "terminal"


@dataclass(frozen=True)
class FailureClassification:
    """Classification result for runtime/offline workflow failures."""

    failure_class: str
    error_code: str


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
    dataset_source_path: str = ""
    watermark_start: str | None = None
    watermark_end: str | None = None
    max_records: int | None = None
    source_cursor: str | None = None
    trigger: str = "manual"
    requested_by: str = "pipeline.offline_trigger"
    source_event_id: str | None = None


@dataclass
class MentalModelParams:
    """Input contract for repository mental-model refresh workflow runs."""

    repo_id: str
    from_sha: str | None = None
    to_sha: str | None = None


@dataclass
class EvaluationRefreshParams:
    """Input contract for monthly benchmark evaluation refresh workflow runs."""

    dataset_name: str
    dataset_version: str
    trigger: str = "monthly_schedule"
    requested_by: str = "pipeline.evaluation_refresh_trigger"
    source_event_id: str | None = None


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
            _log_workflow_warning(
                "pipeline.runtime.workflow_id_mismatch",
                repo_id=params.repo_id,
                workflow_id=current_workflow_id,
                job_id=current_run_id,
                canonical_workflow_id=canonical_workflow_id,
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
        _log_workflow_info(
            "pipeline.runtime.start",
            repo_id=params.repo_id,
            workflow_id=current_workflow_id,
            job_id=current_run_id,
            ref=params.ref,
            force_reindex=params.force_reindex,
        )
        run_started_at = _workflow_now_utc()

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
                _log_workflow_info(
                    "pipeline.runtime.stage.dispatch",
                    repo_id=params.repo_id,
                    workflow_id=current_workflow_id,
                    job_id=current_run_id,
                    stage=stage.value,
                    progress_pct=progress_pct,
                    activity=str(stage_activity),
                )
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
                _log_workflow_info(
                    "pipeline.runtime.stage.complete",
                    repo_id=params.repo_id,
                    workflow_id=current_workflow_id,
                    job_id=current_run_id,
                    stage=stage.value,
                    progress_pct=progress_pct,
                )
        except asyncio.CancelledError as exc:
            classification = await _persist_runtime_failure(
                stage_payload=stage_payload,
                stage=current_stage,
                progress_pct=current_progress,
                exc=exc,
            )
            await _persist_pipeline_run_metrics_best_effort(
                stage_payload=stage_payload,
                workflow_type="RuntimeIndexWorkflow",
                status=IndexStatus.FAILED.value,
                started_at=run_started_at,
                finished_at=_workflow_now_utc(),
                records_in=_extract_runtime_records_in(stage_payload),
                records_out=_extract_runtime_records_out(stage_payload),
                failure_count=1,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            raise
        except Exception as exc:
            classification = await _persist_runtime_failure(
                stage_payload=stage_payload,
                stage=current_stage,
                progress_pct=current_progress,
                exc=exc,
            )
            await _persist_pipeline_run_metrics_best_effort(
                stage_payload=stage_payload,
                workflow_type="RuntimeIndexWorkflow",
                status=IndexStatus.FAILED.value,
                started_at=run_started_at,
                finished_at=_workflow_now_utc(),
                records_in=_extract_runtime_records_in(stage_payload),
                records_out=_extract_runtime_records_out(stage_payload),
                failure_count=1,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
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
        _log_workflow_info(
            "pipeline.runtime.complete",
            repo_id=params.repo_id,
            workflow_id=current_workflow_id,
            job_id=current_run_id,
            status=IndexStatus.READY.value,
            snapshot_sha=stage_payload.get("snapshot_sha"),
        )
        await _persist_pipeline_run_metrics_best_effort(
            stage_payload=stage_payload,
            workflow_type="RuntimeIndexWorkflow",
            status=IndexStatus.READY.value,
            started_at=run_started_at,
            finished_at=_workflow_now_utc(),
            records_in=_extract_runtime_records_in(stage_payload),
            records_out=_extract_runtime_records_out(stage_payload),
            failure_count=0,
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
        workflow_info = workflow.info()
        correlation = _workflow_correlation(
            workflow_id=workflow_info.workflow_id,
            job_id=workflow_info.run_id,
        )
        stage_payload: dict[str, object] = {
            "dataset_name": params.dataset_name,
            "dataset_version": params.dataset_version,
            "dataset_source_path": params.dataset_source_path,
            "watermark_start": params.watermark_start,
            "watermark_end": params.watermark_end,
            "max_records": params.max_records,
            "source_cursor": params.source_cursor,
            "trigger": params.trigger,
            "requested_by": params.requested_by,
            "source_event_id": params.source_event_id,
            "workflow_id": workflow_info.workflow_id,
            "job_id": workflow_info.run_id,
        }
        _log_workflow_info(
            "pipeline.offline.start",
            **correlation,
            dataset_name=params.dataset_name,
            dataset_version=params.dataset_version,
            watermark_start=params.watermark_start,
            watermark_end=params.watermark_end,
            max_records=params.max_records,
            source_cursor=params.source_cursor,
            trigger=params.trigger,
            requested_by=params.requested_by,
            source_event_id=params.source_event_id,
        )
        run_started_at = _workflow_now_utc()
        try:
            stage_payload = await workflow.execute_activity(
                ingest_activity,
                stage_payload,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=_OFFLINE_RETRY_POLICY,
            )
            stage_payload = await workflow.execute_activity(
                clean_activity,
                stage_payload,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=_OFFLINE_RETRY_POLICY,
            )
            stage_payload = await workflow.execute_activity(
                transform_activity,
                stage_payload,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=_OFFLINE_RETRY_POLICY,
            )
            stage_payload = await workflow.execute_activity(
                store_activity,
                stage_payload,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=_OFFLINE_RETRY_POLICY,
            )
        except asyncio.CancelledError as exc:
            classification = _classify_failure(exc)
            _log_workflow_warning(
                "pipeline.offline.cancelled",
                **correlation,
                failure_class=classification.failure_class,
                error_code=classification.error_code,
            )
            await _persist_pipeline_run_metrics_best_effort(
                stage_payload=stage_payload,
                workflow_type="OfflineDatasetWorkflow",
                status=IndexStatus.FAILED.value,
                started_at=run_started_at,
                finished_at=_workflow_now_utc(),
                records_in=_extract_offline_records_in(stage_payload),
                records_out=_extract_offline_records_out(stage_payload),
                failure_count=1,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            raise
        except Exception as exc:
            classification = _classify_failure(exc)
            _log_workflow_error(
                "pipeline.offline.failed",
                **correlation,
                failure_class=classification.failure_class,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            await _persist_pipeline_run_metrics_best_effort(
                stage_payload=stage_payload,
                workflow_type="OfflineDatasetWorkflow",
                status=IndexStatus.FAILED.value,
                started_at=run_started_at,
                finished_at=_workflow_now_utc(),
                records_in=_extract_offline_records_in(stage_payload),
                records_out=_extract_offline_records_out(stage_payload),
                failure_count=1,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            raise
        _log_workflow_info(
            "pipeline.offline.complete",
            **correlation,
            status=IndexStatus.READY.value,
            dataset_name=params.dataset_name,
            records_out=(stage_payload.get("transform_stats") or {}).get(
                "dataset_instance_count"
            ),
        )
        await _persist_pipeline_run_metrics_best_effort(
            stage_payload=stage_payload,
            workflow_type="OfflineDatasetWorkflow",
            status=IndexStatus.READY.value,
            started_at=run_started_at,
            finished_at=_workflow_now_utc(),
            records_in=_extract_offline_records_in(stage_payload),
            records_out=_extract_offline_records_out(stage_payload),
            failure_count=_extract_offline_failure_count(stage_payload),
        )
        return {"status": IndexStatus.READY.value}


@workflow.defn
class MentalModelWorkflow:
    """Workflow for computing repository mental-model artifacts."""

    @workflow.run
    async def run(self, params: MentalModelParams) -> dict[str, str]:
        """Execute mental-model activity for a repository commit range."""
        workflow_info = workflow.info()
        correlation = _workflow_correlation(
            repo_id=params.repo_id,
            workflow_id=workflow_info.workflow_id,
            job_id=workflow_info.run_id,
        )
        payload = {
            "repo_id": params.repo_id,
            "from_sha": params.from_sha,
            "to_sha": params.to_sha,
            "workflow_id": workflow_info.workflow_id,
            "job_id": workflow_info.run_id,
        }
        _log_workflow_info(
            "pipeline.mental_model.start",
            **correlation,
            from_sha=params.from_sha,
            to_sha=params.to_sha,
        )
        run_started_at = _workflow_now_utc()
        try:
            await workflow.execute_activity(
                mental_model_activity,
                payload,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=_MENTAL_MODEL_RETRY_POLICY,
            )
        except asyncio.CancelledError as exc:
            classification = _classify_failure(exc)
            _log_workflow_warning(
                "pipeline.mental_model.cancelled",
                **correlation,
                failure_class=classification.failure_class,
                error_code=classification.error_code,
            )
            await _persist_pipeline_run_metrics_best_effort(
                stage_payload=payload,
                workflow_type="MentalModelWorkflow",
                status=IndexStatus.FAILED.value,
                started_at=run_started_at,
                finished_at=_workflow_now_utc(),
                records_in=None,
                records_out=None,
                failure_count=1,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            raise
        except Exception as exc:
            classification = _classify_failure(exc)
            _log_workflow_error(
                "pipeline.mental_model.failed",
                **correlation,
                failure_class=classification.failure_class,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            await _persist_pipeline_run_metrics_best_effort(
                stage_payload=payload,
                workflow_type="MentalModelWorkflow",
                status=IndexStatus.FAILED.value,
                started_at=run_started_at,
                finished_at=_workflow_now_utc(),
                records_in=None,
                records_out=None,
                failure_count=1,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            raise
        _log_workflow_info(
            "pipeline.mental_model.complete",
            **correlation,
            status=IndexStatus.READY.value,
        )
        await _persist_pipeline_run_metrics_best_effort(
            stage_payload=payload,
            workflow_type="MentalModelWorkflow",
            status=IndexStatus.READY.value,
            started_at=run_started_at,
            finished_at=_workflow_now_utc(),
            records_in=None,
            records_out=None,
            failure_count=0,
        )
        return {"status": IndexStatus.READY.value}


@workflow.defn
class EvaluationRefreshWorkflow:
    """Workflow for periodic evaluation refresh over pinned benchmark snapshots."""

    @workflow.run
    async def run(self, params: EvaluationRefreshParams) -> dict[str, str]:
        """Execute monthly evaluation refresh metadata run for pinned dataset slice."""
        workflow_info = workflow.info()
        correlation = _workflow_correlation(
            workflow_id=workflow_info.workflow_id,
            job_id=workflow_info.run_id,
        )
        payload: dict[str, object] = {
            "dataset_name": params.dataset_name,
            "dataset_version": params.dataset_version,
            "trigger": params.trigger,
            "requested_by": params.requested_by,
            "source_event_id": params.source_event_id,
            "workflow_id": workflow_info.workflow_id,
            "job_id": workflow_info.run_id,
        }
        _log_workflow_info(
            "pipeline.evaluation_refresh.start",
            **correlation,
            dataset_name=params.dataset_name,
            dataset_version=params.dataset_version,
            trigger=params.trigger,
            requested_by=params.requested_by,
            source_event_id=params.source_event_id,
        )
        run_started_at = _workflow_now_utc()
        try:
            payload = await workflow.execute_activity(
                evaluation_refresh_activity,
                payload,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=_EVALUATION_REFRESH_RETRY_POLICY,
            )
            payload = await workflow.execute_activity(
                baseline_evaluation_activity,
                payload,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=_EVALUATION_REFRESH_RETRY_POLICY,
            )
        except asyncio.CancelledError as exc:
            classification = _classify_failure(exc)
            _log_workflow_warning(
                "pipeline.evaluation_refresh.cancelled",
                **correlation,
                failure_class=classification.failure_class,
                error_code=classification.error_code,
            )
            await _persist_pipeline_run_metrics_best_effort(
                stage_payload=payload,
                workflow_type="EvaluationRefreshWorkflow",
                status=IndexStatus.FAILED.value,
                started_at=run_started_at,
                finished_at=_workflow_now_utc(),
                records_in=None,
                records_out=None,
                failure_count=1,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            raise
        except Exception as exc:
            classification = _classify_failure(exc)
            _log_workflow_error(
                "pipeline.evaluation_refresh.failed",
                **correlation,
                failure_class=classification.failure_class,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            await _persist_pipeline_run_metrics_best_effort(
                stage_payload=payload,
                workflow_type="EvaluationRefreshWorkflow",
                status=IndexStatus.FAILED.value,
                started_at=run_started_at,
                finished_at=_workflow_now_utc(),
                records_in=None,
                records_out=None,
                failure_count=1,
                error_code=classification.error_code,
                error_message=_format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            )
            raise
        _log_workflow_info(
            "pipeline.evaluation_refresh.complete",
            **correlation,
            status=IndexStatus.READY.value,
            dataset_name=params.dataset_name,
            dataset_version=params.dataset_version,
            dataset_instance_count=(payload.get("evaluation_refresh_stats") or {}).get(
                "dataset_instance_count"
            ),
            fail_to_pass_rate=(payload.get("baseline_evaluation_stats") or {}).get(
                "fail_to_pass_rate"
            ),
            regression_rate=(payload.get("baseline_evaluation_stats") or {}).get(
                "regression_rate"
            ),
        )
        evaluation_records = _extract_evaluation_records(payload)
        await _persist_pipeline_run_metrics_best_effort(
            stage_payload=payload,
            workflow_type="EvaluationRefreshWorkflow",
            status=IndexStatus.READY.value,
            started_at=run_started_at,
            finished_at=_workflow_now_utc(),
            records_in=evaluation_records,
            records_out=evaluation_records,
            failure_count=0,
        )
        return {"status": IndexStatus.READY.value}


async def _persist_runtime_failure(
    *,
    stage_payload: dict[str, object],
    stage: IndexStage,
    progress_pct: int,
    exc: BaseException,
) -> FailureClassification:
    """Persist runtime workflow failure with retryability classification metadata."""
    classification = _classify_failure(exc)
    correlation = _workflow_correlation(
        repo_id=_coerce_str(stage_payload.get("repo_id")),
        workflow_id=_coerce_str(stage_payload.get("workflow_id")),
        job_id=_coerce_str(stage_payload.get("job_id")),
    )
    try:
        await workflow.execute_activity(
            persist_runtime_index_failure_activity,
            {
                **stage_payload,
                "stage": stage.value,
                "progress_pct": progress_pct,
                "error_code": classification.error_code,
                "error_message": _format_failure_message(
                    exc=exc,
                    failure_class=classification.failure_class,
                ),
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_PERSIST_RETRY_POLICY,
            cancellation_type=workflow.ActivityCancellationType.ABANDON,
        )
    except Exception as persist_exc:
        _log_workflow_error(
            "pipeline.runtime.failure_persist_failed",
            **correlation,
            failure_class=classification.failure_class,
            error_code=classification.error_code,
            stage=stage.value,
            persist_error=str(persist_exc)[:500],
        )
    _log_workflow_error(
        "pipeline.runtime.failed",
        **correlation,
        failure_class=classification.failure_class,
        error_code=classification.error_code,
        stage=stage.value,
    )
    return classification


def _classify_failure(exc: BaseException) -> FailureClassification:
    """Classify failures into `retryable` vs `terminal` and choose error code."""
    root = _unwrap_exception(exc)

    if _is_cancelled(exc) or _is_cancelled(root):
        return FailureClassification(
            failure_class=_FAILURE_CLASS_TERMINAL,
            error_code="RUNTIME_INDEX_TERMINAL_CANCELLED",
        )

    if isinstance(root, ValueError):
        return FailureClassification(
            failure_class=_FAILURE_CLASS_TERMINAL,
            error_code="RUNTIME_INDEX_TERMINAL_VALIDATION",
        )

    if isinstance(root, temporal_exceptions.ApplicationError):
        if root.non_retryable:
            return FailureClassification(
                failure_class=_FAILURE_CLASS_TERMINAL,
                error_code="RUNTIME_INDEX_TERMINAL_APPLICATION",
            )
        return FailureClassification(
            failure_class=_FAILURE_CLASS_RETRYABLE,
            error_code="RUNTIME_INDEX_RETRYABLE_APPLICATION",
        )

    if isinstance(root, temporal_exceptions.TimeoutError):
        return FailureClassification(
            failure_class=_FAILURE_CLASS_RETRYABLE,
            error_code="RUNTIME_INDEX_RETRYABLE_TIMEOUT",
        )

    if isinstance(root, temporal_exceptions.ServerError):
        return FailureClassification(
            failure_class=_FAILURE_CLASS_RETRYABLE,
            error_code="RUNTIME_INDEX_RETRYABLE_SERVER",
        )

    if isinstance(root, (OSError, ConnectionError)):
        return FailureClassification(
            failure_class=_FAILURE_CLASS_RETRYABLE,
            error_code="RUNTIME_INDEX_RETRYABLE_IO",
        )

    return FailureClassification(
        failure_class=_FAILURE_CLASS_TERMINAL,
        error_code="RUNTIME_INDEX_TERMINAL_UNKNOWN",
    )


def _format_failure_message(*, exc: BaseException, failure_class: str) -> str:
    """Build bounded failure message text with classification prefix."""
    root = _unwrap_exception(exc)
    root_message = str(root).strip()
    if not root_message:
        root_message = root.__class__.__name__
    formatted = f"[{failure_class}] {root.__class__.__name__}: {root_message}"
    return formatted[:2000]


def _unwrap_exception(exc: BaseException) -> BaseException:
    """Unwrap nested Temporal failure causes to deepest known exception."""
    current: BaseException = exc
    for _ in range(8):
        cause = getattr(current, "cause", None) or getattr(current, "__cause__", None)
        if cause is None or not isinstance(cause, BaseException):
            break
        current = cause
    return current


def _is_cancelled(exc: BaseException) -> bool:
    """Return whether an exception represents a cancellation/termination path."""
    if isinstance(exc, asyncio.CancelledError):
        return True
    if isinstance(exc, temporal_exceptions.TerminatedError):
        return True
    return temporal_exceptions.is_cancelled_exception(exc)


def _workflow_correlation(
    *,
    repo_id: str | None = None,
    workflow_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, str | None]:
    """Build canonical workflow correlation field payload."""
    return {
        "repo_id": repo_id,
        "workflow_id": workflow_id,
        "job_id": job_id,
    }


def _coerce_str(value: Any) -> str | None:
    """Convert to non-empty string or `None`."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _log_workflow_info(event: str, **fields: Any) -> None:
    """Emit a structured info-level workflow log event."""
    workflow.logger.info(structured_event(event, **fields))


def _log_workflow_warning(event: str, **fields: Any) -> None:
    """Emit a structured warning-level workflow log event."""
    workflow.logger.warning(structured_event(event, **fields))


def _log_workflow_error(event: str, **fields: Any) -> None:
    """Emit a structured error-level workflow log event."""
    workflow.logger.error(structured_event(event, **fields))


async def _persist_pipeline_run_metrics_best_effort(
    *,
    stage_payload: dict[str, object],
    workflow_type: str,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    records_in: int | None,
    records_out: int | None,
    failure_count: int | None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Persist pipeline run metrics while avoiding workflow failure masking."""
    payload = {
        **stage_payload,
        "workflow_type": workflow_type,
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": _duration_ms(started_at=started_at, finished_at=finished_at),
        "records_in": records_in,
        "records_out": records_out,
        "failure_count": failure_count,
        "error_code": error_code,
        "error_message": error_message,
    }
    correlation = _workflow_correlation(
        repo_id=_coerce_str(stage_payload.get("repo_id")),
        workflow_id=_coerce_str(stage_payload.get("workflow_id")),
        job_id=_coerce_str(stage_payload.get("job_id")),
    )
    try:
        await workflow.execute_activity(
            persist_pipeline_run_metrics_activity,
            payload,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_PERSIST_RETRY_POLICY,
            cancellation_type=workflow.ActivityCancellationType.ABANDON,
        )
    except Exception as exc:
        _log_workflow_error(
            "pipeline.metrics.persist_failed",
            **correlation,
            workflow_type=workflow_type,
            status=status,
            persist_error=str(exc)[:500],
        )


def _workflow_now_utc() -> datetime:
    """Return workflow clock time with UTC fallback for unit tests."""
    try:
        return workflow.now()
    except Exception:
        return datetime.now(timezone.utc)


def _duration_ms(*, started_at: datetime, finished_at: datetime) -> int:
    """Compute non-negative duration in milliseconds between two timestamps."""
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def _extract_runtime_records_in(payload: dict[str, object]) -> int | None:
    """Extract runtime ingest record count from stage payload stats."""
    ingest_stats = payload.get("ingest_stats")
    if not isinstance(ingest_stats, dict):
        return None
    value = ingest_stats.get("file_count")
    return _coerce_non_negative_int(value)


def _extract_runtime_records_out(payload: dict[str, object]) -> int | None:
    """Extract runtime output record count from stage payload stats."""
    transform_stats = payload.get("transform_stats")
    if not isinstance(transform_stats, dict):
        return None
    value = transform_stats.get("chunk_count")
    return _coerce_non_negative_int(value)


def _extract_offline_records_in(payload: dict[str, object]) -> int | None:
    """Extract offline ingest record count from stage payload stats."""
    ingest_stats = payload.get("ingest_stats")
    if not isinstance(ingest_stats, dict):
        return None
    value = ingest_stats.get("records_in")
    return _coerce_non_negative_int(value)


def _extract_offline_records_out(payload: dict[str, object]) -> int | None:
    """Extract offline output record count from stage payload stats."""
    transform_stats = payload.get("transform_stats")
    if not isinstance(transform_stats, dict):
        return None
    value = transform_stats.get("records_out")
    if value is None:
        value = transform_stats.get("dataset_instance_count")
    return _coerce_non_negative_int(value)


def _extract_offline_failure_count(payload: dict[str, object]) -> int | None:
    """Extract offline invalid-row count as pipeline run failure count."""
    clean_stats = payload.get("clean_stats")
    if not isinstance(clean_stats, dict):
        return None
    value = clean_stats.get("invalid_record_count")
    return _coerce_non_negative_int(value)


def _extract_evaluation_records(payload: dict[str, object]) -> int | None:
    """Extract evaluation slice cardinality from refresh stats payload."""
    stats = payload.get("evaluation_refresh_stats")
    if not isinstance(stats, dict):
        return None
    value = stats.get("dataset_instance_count")
    return _coerce_non_negative_int(value)


def _coerce_non_negative_int(value: object) -> int | None:
    """Convert one scalar into non-negative integer or `None`."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        coerced = int(value)
        return coerced if coerced >= 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            coerced = int(stripped)
        except ValueError:
            return None
        return coerced if coerced >= 0 else None
    return None
