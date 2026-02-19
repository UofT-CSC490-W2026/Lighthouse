"""Temporal workflow definitions for pipeline execution."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import exceptions as temporal_exceptions
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
        except asyncio.CancelledError as exc:
            await _persist_runtime_failure(
                stage_payload=stage_payload,
                stage=current_stage,
                progress_pct=current_progress,
                exc=exc,
            )
            raise
        except Exception as exc:
            await _persist_runtime_failure(
                stage_payload=stage_payload,
                stage=current_stage,
                progress_pct=current_progress,
                exc=exc,
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
        try:
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
        except asyncio.CancelledError as exc:
            classification = _classify_failure(exc)
            workflow.logger.warning(
                "OfflineDatasetWorkflow cancelled (class=%s code=%s)",
                classification.failure_class,
                classification.error_code,
            )
            raise
        except Exception as exc:
            classification = _classify_failure(exc)
            workflow.logger.error(
                "OfflineDatasetWorkflow failed (class=%s code=%s): %s",
                classification.failure_class,
                classification.error_code,
                _format_failure_message(
                    exc=exc, failure_class=classification.failure_class
                ),
            )
            raise
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
        try:
            await workflow.execute_activity(
                mental_model_activity,
                payload,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=_MENTAL_MODEL_RETRY_POLICY,
            )
        except asyncio.CancelledError as exc:
            classification = _classify_failure(exc)
            workflow.logger.warning(
                "MentalModelWorkflow cancelled (class=%s code=%s)",
                classification.failure_class,
                classification.error_code,
            )
            raise
        except Exception as exc:
            classification = _classify_failure(exc)
            workflow.logger.error(
                "MentalModelWorkflow failed (class=%s code=%s): %s",
                classification.failure_class,
                classification.error_code,
                _format_failure_message(
                    exc=exc, failure_class=classification.failure_class
                ),
            )
            raise
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
        workflow.logger.error(
            "Failed to persist runtime failure (class=%s code=%s stage=%s): %s",
            classification.failure_class,
            classification.error_code,
            stage.value,
            str(persist_exc)[:500],
        )
    workflow.logger.error(
        "RuntimeIndexWorkflow failed (class=%s code=%s stage=%s)",
        classification.failure_class,
        classification.error_code,
        stage.value,
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
