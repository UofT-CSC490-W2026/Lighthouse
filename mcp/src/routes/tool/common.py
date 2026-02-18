"""Shared tool-route helpers for index-state gating and response shaping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import quote

from ...errors import (
    BackendUnavailableError,
    RequestValidationAppError,
    WorkflowExecutionError,
)
from ...services import index_control_service
from ...types import (
    IndexStatus,
    StartIndexJobRequest,
    ToolIndexMetadata,
    ToolResponseEnvelope,
    ToolRetryHint,
)

TResult = TypeVar("TResult")


@dataclass(frozen=True, slots=True)
class ToolGateDecision:
    """Result of evaluating whether a tool call may execute against current index state."""

    index: ToolIndexMetadata
    allow_execute: bool
    message: str | None = None
    retry: ToolRetryHint | None = None


def build_tool_envelope(
    *,
    index: ToolIndexMetadata,
    result: TResult | None = None,
    message: str | None = None,
    retry: ToolRetryHint | None = None,
) -> ToolResponseEnvelope[TResult]:
    """Build a canonical tool response envelope with index metadata."""
    return ToolResponseEnvelope(
        index=index,
        result=result,
        message=message,
        retry=retry,
    )


async def gate_tool_request(
    *,
    repo_id: str,
    ref: str,
    tool_name: str,
    auto_start_on_missing: bool = True,
) -> ToolGateDecision:
    """Gate a tool request by current index state and optional auto-start policy."""
    try:
        state = await index_control_service.get_repo_state(repo_id=repo_id, ref=ref)
    except ValueError as exc:
        raise RequestValidationAppError(str(exc)) from exc
    except RuntimeError as exc:
        raise BackendUnavailableError("Index control backend unavailable") from exc

    metadata = ToolIndexMetadata(
        status=state.status,
        repo_id=state.repo_id,
        ref=state.ref,
        snapshot_sha=state.snapshot_sha,
        job_id=state.active_job_id,
    )

    if state.status == IndexStatus.READY:
        return ToolGateDecision(index=metadata, allow_execute=True)

    if state.status == IndexStatus.STALE:
        return ToolGateDecision(
            index=metadata,
            allow_execute=True,
            message="Index is stale; serving best-effort context.",
        )

    if state.status == IndexStatus.PENDING:
        return ToolGateDecision(
            index=metadata,
            allow_execute=False,
            message="Index build is in progress.",
        )

    if state.status == IndexStatus.FAILED:
        return ToolGateDecision(
            index=metadata,
            allow_execute=False,
            message="Indexing failed; retry the index workflow before requesting tool context.",
            retry=_retry_hint(repo_id=state.repo_id, ref=state.ref),
        )

    if state.status == IndexStatus.NOT_FOUND and auto_start_on_missing:
        try:
            start = await index_control_service.start_job(
                StartIndexJobRequest(
                    repo_id=repo_id,
                    repo_url=_default_repo_url(repo_id),
                    ref=ref,
                    trigger="mcp_auto",
                    requested_by=tool_name,
                    force_reindex=False,
                )
            )
        except ValueError as exc:
            raise RequestValidationAppError(str(exc)) from exc
        except RuntimeError as exc:
            raise BackendUnavailableError("Index control backend unavailable") from exc
        except Exception as exc:
            raise WorkflowExecutionError(
                "Failed to start runtime indexing workflow",
            ) from exc

        return ToolGateDecision(
            index=ToolIndexMetadata(
                status=IndexStatus.PENDING,
                repo_id=repo_id,
                ref=ref,
                snapshot_sha=None,
                job_id=start.job_id,
            ),
            allow_execute=False,
            message="Index not found; started runtime indexing job.",
        )

    if state.status == IndexStatus.NOT_FOUND:
        return ToolGateDecision(
            index=metadata,
            allow_execute=False,
            message="Index not found for repository/ref target.",
        )

    raise WorkflowExecutionError(
        f"Unsupported index status encountered: {state.status.value}",
    )


def _default_repo_url(repo_id: str) -> str:
    """Derive a default repository URL from `repo_id` when explicit URL is absent."""
    normalized = repo_id.strip()
    if normalized.startswith("https://") or normalized.startswith("http://"):
        return normalized
    return f"https://github.com/{normalized}"


def _retry_hint(*, repo_id: str, ref: str) -> ToolRetryHint:
    """Build retry hint metadata for failed index states."""
    encoded_repo_id = quote(repo_id, safe="/")
    encoded_ref = quote(ref, safe="")
    return ToolRetryHint(
        endpoint=f"/v1/index/repos/{encoded_repo_id}/retry?ref={encoded_ref}",
        method="POST",
    )
