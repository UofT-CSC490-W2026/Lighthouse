"""Temporal activities for the standalone pipeline worker."""

from typing import Any

from temporalio import activity

from .contracts import IndexStage
from .persistence import (
    record_runtime_index_failed,
    record_runtime_index_progress,
    record_runtime_index_ready,
    record_runtime_index_started,
)


@activity.defn(name="ingest_activity")
async def ingest_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "ingest", "ok": True, "payload": payload}


@activity.defn(name="clean_activity")
async def clean_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "clean", "ok": True, "payload": payload}


@activity.defn(name="transform_activity")
async def transform_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "transform", "ok": True, "payload": payload}


@activity.defn(name="store_activity")
async def store_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "store", "ok": True, "payload": payload}


@activity.defn(name="mental_model_activity")
async def mental_model_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "mental_model", "ok": True, "payload": payload}


@activity.defn(name="persist_runtime_index_start_activity")
async def persist_runtime_index_start_activity(payload: dict[str, Any]) -> dict[str, Any]:
    await record_runtime_index_started(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
    )
    return {"stage": "persist_start", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_success_activity")
async def persist_runtime_index_success_activity(payload: dict[str, Any]) -> dict[str, Any]:
    await record_runtime_index_ready(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
        snapshot_sha=payload.get("snapshot_sha"),
    )
    return {"stage": "persist_success", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_failure_activity")
async def persist_runtime_index_failure_activity(payload: dict[str, Any]) -> dict[str, Any]:
    stage_raw = payload.get("stage")
    stage = IndexStage(stage_raw) if stage_raw else None
    await record_runtime_index_failed(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
        stage=stage,
        error_code=_require_str(payload, "error_code"),
        error_message=_require_str(payload, "error_message"),
        progress_pct=_require_progress(payload, "progress_pct"),
    )
    return {"stage": "persist_failure", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_progress_activity")
async def persist_runtime_index_progress_activity(payload: dict[str, Any]) -> dict[str, Any]:
    stage = IndexStage(_require_str(payload, "stage"))
    progress = _require_progress(payload, "progress_pct")
    await record_runtime_index_progress(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
        stage=stage,
        progress_pct=progress,
    )
    return {
        "stage": "persist_progress",
        "ok": True,
        "job_id": payload["job_id"],
        "progress_pct": progress,
    }


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"payload field '{key}' is required")
    return value


def _require_progress(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"payload field '{key}' must be an integer")
    if value < 0 or value > 100:
        raise ValueError(f"payload field '{key}' must be between 0 and 100")
    return value
