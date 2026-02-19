"""Temporal activities for the standalone pipeline worker."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import re
from pathlib import Path
import tarfile
from typing import Any
from urllib.parse import urlparse
from git import Repo
from temporalio import activity

from .config import settings
from .connectors import GitHubConnector, S3Connector
from .contracts import IndexStage
from .offline_sources import SwebenchSnapshot, SwebenchSnapshotAdapter
from .observability import correlation_from_payload, structured_event
from .persistence import (
    DatasetInstanceWrite,
    record_runtime_index_failed,
    record_runtime_index_progress,
    record_runtime_index_ready,
    record_runtime_index_started,
    upsert_dataset_instances,
)

_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_MAX_FILE_BYTES = 256 * 1024
_MAX_FILE_COUNT = 1500
_MAX_TOTAL_TEXT_BYTES = 12 * 1024 * 1024
_CHUNK_SIZE_CHARS = 1200
_CHUNK_OVERLAP_CHARS = 200
_MIN_CHUNK_CHARS = 120
_OFFLINE_SUPPORTED_DATASETS = {"swebench", "swe-bench", "swe_bench"}
_OFFLINE_SUPPORTED_DATASET_KEYS = frozenset(
    re.sub(r"[-_]+", "", name.strip().lower())
    for name in _OFFLINE_SUPPORTED_DATASETS
)
_OFFLINE_SCHEMA_VERSION = "offline-clean-schema/v1"
_OFFLINE_REPO_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
_OFFLINE_TOKEN_PATTERN = re.compile(r"^[a-z0-9._-]+$")
_OFFLINE_SNAPSHOT_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")

_SKIP_PREFIXES = (
    ".git/",
    ".hg/",
    ".svn/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    ".mypy_cache/",
    ".pytest_cache/",
    "build/",
    "dist/",
    ".idea/",
    ".vscode/",
)
_SUPPORTED_SUFFIXES = {
    ".c",
    ".cfg",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_SUPPORTED_FILENAMES = {
    "Dockerfile",
    "Makefile",
    "README",
    "README.md",
    "go.mod",
    "go.sum",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
}
_GITHUB_CONNECTOR = GitHubConnector()
_S3_CONNECTOR = S3Connector(region_name=settings.aws_region)
_SWEBENCH_SNAPSHOT_ADAPTER = SwebenchSnapshotAdapter()


@activity.defn(name="ingest_activity")
async def ingest_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Ingest raw source inputs for the current workflow payload."""
    correlation = correlation_from_payload(payload)
    _log_activity_info("pipeline.ingest.start", **correlation)
    if _is_runtime_payload(payload):
        repo_id = _require_str(payload, "repo_id")
        repo_url = _require_str(payload, "repo_url")
        ref = _coerce_ref(payload.get("ref"))
        artifact_dir = _runtime_artifact_dir(payload)
        ingest_path = artifact_dir / "ingest_files.jsonl"

        snapshot_sha, files = _load_repo_files(
            repo_url=repo_url,
            ref=ref,
            payload=payload,
        )
        _write_jsonl(ingest_path, files)

        result = {
            **payload,
            "stage": "ingest",
            "ok": True,
            "repo_id": repo_id,
            "ref": ref,
            "snapshot_sha": snapshot_sha,
            "artifact_dir": str(artifact_dir),
            "ingest_path": str(ingest_path),
            "ingest_stats": {
                "file_count": len(files),
                "total_text_bytes": sum(item["size_bytes"] for item in files),
            },
        }
        _log_activity_info(
            "pipeline.ingest.complete",
            **correlation,
            file_count=result["ingest_stats"]["file_count"],
            total_text_bytes=result["ingest_stats"]["total_text_bytes"],
            snapshot_sha=result.get("snapshot_sha"),
            mode="runtime",
        )
        return result

    if _is_offline_payload(payload):
        result = _ingest_offline_dataset(payload)
        _log_activity_info(
            "pipeline.ingest.complete",
            **correlation,
            records_in=result["ingest_stats"]["records_in"],
            source_mode=result["ingest_stats"]["source_mode"],
            mode="offline",
        )
        return result

    _log_activity_info("pipeline.ingest.skip_unknown_payload", **correlation)
    return {"stage": "ingest", "ok": True, "payload": payload}


@activity.defn(name="clean_activity")
async def clean_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean and normalize ingested payload artifacts."""
    correlation = correlation_from_payload(payload)
    _log_activity_info("pipeline.clean.start", **correlation)
    if _is_runtime_payload(payload):
        ingest_path = Path(_require_str(payload, "ingest_path"))
        artifact_dir = Path(_require_str(payload, "artifact_dir"))
        clean_path = artifact_dir / "clean_documents.jsonl"

        seen_paths: set[str] = set()
        cleaned_docs: list[dict[str, Any]] = []
        dropped_records = 0
        for record in _read_jsonl(ingest_path):
            path = str(record.get("path") or "").strip()
            content = str(record.get("content") or "")
            if not path or path in seen_paths:
                dropped_records += 1
                continue
            normalized = _normalize_source_text(content)
            if not normalized:
                dropped_records += 1
                continue
            seen_paths.add(path)
            cleaned_docs.append(
                {
                    "path": path,
                    "content": normalized,
                    "size_bytes": len(normalized.encode("utf-8")),
                    "line_count": normalized.count("\n") + 1,
                    "language": _infer_language(path),
                }
            )

        _write_jsonl(clean_path, cleaned_docs)
        result = {
            **payload,
            "stage": "clean",
            "ok": True,
            "clean_path": str(clean_path),
            "clean_stats": {
                "input_file_count": len(seen_paths) + dropped_records,
                "document_count": len(cleaned_docs),
                "dropped_records": dropped_records,
            },
        }
        _log_activity_info(
            "pipeline.clean.complete",
            **correlation,
            document_count=result["clean_stats"]["document_count"],
            dropped_records=result["clean_stats"]["dropped_records"],
            mode="runtime",
        )
        return result

    if _is_offline_payload(payload):
        result = _clean_offline_dataset(payload)
        _log_activity_info(
            "pipeline.clean.complete",
            **correlation,
            records_out=result["clean_stats"]["clean_record_count"],
            invalid_records=result["clean_stats"]["invalid_record_count"],
            mode="offline",
        )
        return result

    _log_activity_info("pipeline.clean.skip_unknown_payload", **correlation)
    return {"stage": "clean", "ok": True, "payload": payload}


@activity.defn(name="transform_activity")
async def transform_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Transform cleaned inputs into retrieval/evaluation ready structures."""
    correlation = correlation_from_payload(payload)
    _log_activity_info("pipeline.transform.start", **correlation)
    if _is_runtime_payload(payload):
        repo_id = _require_str(payload, "repo_id")
        ref = _coerce_ref(payload.get("ref"))
        clean_path = Path(_require_str(payload, "clean_path"))
        artifact_dir = Path(_require_str(payload, "artifact_dir"))
        transform_path = artifact_dir / "transform_chunks.jsonl"

        chunks: list[dict[str, Any]] = []
        chunk_digest = hashlib.sha1()
        for doc in _read_jsonl(clean_path):
            path = str(doc.get("path") or "")
            content = str(doc.get("content") or "")
            if not path or not content:
                continue
            for index, start, end, text in _chunk_text(
                content=content,
                chunk_size=_CHUNK_SIZE_CHARS,
                overlap=_CHUNK_OVERLAP_CHARS,
                min_chunk_size=_MIN_CHUNK_CHARS,
            ):
                chunk_id = hashlib.sha1(
                    f"{repo_id}:{ref}:{path}:{index}:{start}:{end}".encode("utf-8")
                ).hexdigest()
                text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()
                chunk_digest.update(text_hash.encode("utf-8"))
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "repo_id": repo_id,
                        "ref": ref,
                        "path": path,
                        "chunk_index": index,
                        "start_char": start,
                        "end_char": end,
                        "text": text,
                        "text_hash": text_hash,
                    }
                )

        _write_jsonl(transform_path, chunks)
        result = {
            **payload,
            "stage": "transform",
            "ok": True,
            "transform_path": str(transform_path),
            "transform_stats": {
                "chunk_count": len(chunks),
                "chunk_chars_total": sum(len(chunk["text"]) for chunk in chunks),
                "corpus_hash": chunk_digest.hexdigest(),
            },
        }
        _log_activity_info(
            "pipeline.transform.complete",
            **correlation,
            chunk_count=result["transform_stats"]["chunk_count"],
            chunk_chars_total=result["transform_stats"]["chunk_chars_total"],
            mode="runtime",
        )
        return result

    if _is_offline_payload(payload):
        result = _transform_offline_dataset(payload)
        _log_activity_info(
            "pipeline.transform.complete",
            **correlation,
            dataset_instance_count=result["transform_stats"]["dataset_instance_count"],
            mode="offline",
        )
        return result

    _log_activity_info("pipeline.transform.skip_unknown_payload", **correlation)
    return {"stage": "transform", "ok": True, "payload": payload}


@activity.defn(name="store_activity")
async def store_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist transformed artifacts to configured storage backends."""
    correlation = correlation_from_payload(payload)
    _log_activity_info("pipeline.store.start", **correlation)
    if _is_runtime_payload(payload):
        artifact_dir = Path(_require_str(payload, "artifact_dir"))
        transform_path = Path(_require_str(payload, "transform_path"))
        repo_id = _require_str(payload, "repo_id")
        ref = _coerce_ref(payload.get("ref"))
        job_id = _require_str(payload, "job_id")
        workflow_id = _require_str(payload, "workflow_id")

        snapshot_sha = _resolve_snapshot_sha(
            payload.get("snapshot_sha"),
            corpus_hash=(payload.get("transform_stats") or {}).get("corpus_hash"),
        )
        manifest_path = artifact_dir / "manifest.json"
        manifest = {
            "repo_id": repo_id,
            "ref": ref,
            "job_id": job_id,
            "workflow_id": workflow_id,
            "snapshot_sha": snapshot_sha,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ingest_stats": payload.get("ingest_stats"),
            "clean_stats": payload.get("clean_stats"),
            "transform_stats": payload.get("transform_stats"),
            "transform_path": str(transform_path),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        s3_key_prefix = _maybe_store_runtime_artifacts_to_s3(
            manifest_path=manifest_path,
            chunks_path=transform_path,
            repo_id=repo_id,
            ref=ref,
            job_id=job_id,
        )

        result = {
            **payload,
            "stage": "store",
            "ok": True,
            "snapshot_sha": snapshot_sha,
            "artifact_manifest_path": str(manifest_path),
            "artifact_chunks_path": str(transform_path),
            "store_stats": {
                "s3_key_prefix": s3_key_prefix,
            },
        }
        _log_activity_info(
            "pipeline.store.complete",
            **correlation,
            snapshot_sha=result.get("snapshot_sha"),
            s3_key_prefix=result["store_stats"]["s3_key_prefix"],
            mode="runtime",
        )
        return result

    if _is_offline_payload(payload):
        result = await _store_offline_dataset(payload)
        _log_activity_info(
            "pipeline.store.complete",
            **correlation,
            dataset_name=result.get("dataset_name"),
            records_out=(result.get("transform_stats") or {}).get(
                "dataset_instance_count"
            ),
            s3_key_prefix=result["store_stats"]["s3_key_prefix"],
            dataset_instances_exported=result["store_stats"][
                "dataset_instances_exported"
            ],
            mode="offline",
        )
        return result

    _log_activity_info("pipeline.store.skip_unknown_payload", **correlation)
    return {"stage": "store", "ok": True, "payload": payload}


@activity.defn(name="mental_model_activity")
async def mental_model_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Build or refresh mental-model artifacts for a repository scope."""
    correlation = correlation_from_payload(payload)
    _log_activity_info("pipeline.mental_model.start", **correlation)
    _log_activity_info("pipeline.mental_model.complete", **correlation)
    return {"stage": "mental_model", "ok": True, "payload": payload}


@activity.defn(name="persist_runtime_index_start_activity")
async def persist_runtime_index_start_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist initial runtime index job/state records at workflow start."""
    correlation = correlation_from_payload(payload)
    _log_activity_info("pipeline.persist.start", **correlation)
    await record_runtime_index_started(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
    )
    _log_activity_info("pipeline.persist.start.complete", **correlation)
    return {"stage": "persist_start", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_success_activity")
async def persist_runtime_index_success_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist terminal READY state for a completed runtime index run."""
    correlation = correlation_from_payload(payload)
    _log_activity_info("pipeline.persist.success", **correlation)
    await record_runtime_index_ready(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
        snapshot_sha=payload.get("snapshot_sha"),
    )
    _log_activity_info("pipeline.persist.success.complete", **correlation)
    return {"stage": "persist_success", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_failure_activity")
async def persist_runtime_index_failure_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist terminal FAILED state and error metadata for runtime indexing."""
    correlation = correlation_from_payload(payload)
    _log_activity_info(
        "pipeline.persist.failure",
        **correlation,
        error_code=payload.get("error_code"),
    )
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
    _log_activity_info("pipeline.persist.failure.complete", **correlation)
    return {"stage": "persist_failure", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_progress_activity")
async def persist_runtime_index_progress_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist in-flight stage and progress updates for runtime indexing."""
    correlation = correlation_from_payload(payload)
    stage = IndexStage(_require_str(payload, "stage"))
    progress = _require_progress(payload, "progress_pct")
    _log_activity_info(
        "pipeline.persist.progress",
        **correlation,
        stage=stage.value,
        progress_pct=progress,
    )
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


def _log_activity_info(event: str, **fields: Any) -> None:
    """Emit one structured activity log line."""
    activity.logger.info(structured_event(event, **fields))


def _require_str(payload: dict[str, Any], key: str) -> str:
    """Read and validate a required non-empty string payload field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"payload field '{key}' is required")
    return value


def _require_progress(payload: dict[str, Any], key: str) -> int:
    """Read and validate a required integer progress field in `[0, 100]`."""
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"payload field '{key}' must be an integer")
    if value < 0 or value > 100:
        raise ValueError(f"payload field '{key}' must be between 0 and 100")
    return value


def _is_runtime_payload(payload: dict[str, Any]) -> bool:
    """Return true when payload corresponds to runtime repo indexing."""
    repo_id = payload.get("repo_id")
    repo_url = payload.get("repo_url")
    return isinstance(repo_id, str) and isinstance(repo_url, str)


def _is_offline_payload(payload: dict[str, Any]) -> bool:
    """Return true when payload corresponds to offline dataset processing."""
    dataset_name = payload.get("dataset_name")
    return isinstance(dataset_name, str) and bool(dataset_name.strip())


def _coerce_ref(value: Any) -> str:
    """Normalize git ref value to a non-empty string."""
    if not isinstance(value, str):
        return "main"
    normalized = value.strip()
    return normalized or "main"


def _runtime_artifact_dir(payload: dict[str, Any]) -> Path:
    """Build the runtime activity artifact directory for this job."""
    job_id = _require_str(payload, "job_id")
    base_dir = Path(__file__).resolve().parents[1] / ".artifacts" / "runtime_index"
    artifact_dir = base_dir / _sanitize_identifier(job_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def _offline_artifact_dir(payload: dict[str, Any], *, dataset_key: str) -> Path:
    """Build offline dataset artifact directory for this workflow run."""
    job_id = _require_str(payload, "job_id")
    base_dir = (
        Path(__file__).resolve().parents[1]
        / ".artifacts"
        / "offline_datasets"
        / _sanitize_identifier(dataset_key)
    )
    artifact_dir = base_dir / _sanitize_identifier(job_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def _ingest_offline_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    """Load a benchmark dataset source and write canonical ingest artifacts."""
    dataset_name, dataset_key = _validate_offline_dataset_name(payload)
    dataset_version = _require_str(payload, "dataset_version")
    artifact_dir = _offline_artifact_dir(payload, dataset_key=dataset_key)
    ingest_path = artifact_dir / "offline_ingest_records.jsonl"

    source_snapshot = _load_swebench_source_snapshot(
        payload=payload,
        dataset_version=dataset_version,
    )
    source_records = source_snapshot.records
    ingest_records: list[dict[str, Any]] = []
    for idx, source_row in enumerate(source_records):
        ingest_records.append(
            {
                "record_id": _offline_record_id(
                    source_row,
                    index=idx,
                    dataset_name=dataset_name,
                    dataset_version=dataset_version,
                ),
                "dataset_name": dataset_name,
                "dataset_version": dataset_version,
                "raw": source_row,
            }
        )

    _write_jsonl(ingest_path, ingest_records)
    return {
        **payload,
        "stage": "ingest",
        "ok": True,
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "artifact_dir": str(artifact_dir),
        "ingest_path": str(ingest_path),
        "ingest_stats": {
            "records_in": len(ingest_records),
            "source_mode": source_snapshot.source_mode,
            "source_format": source_snapshot.source_format,
            "source_path": source_snapshot.source_path,
            "snapshot_sha256": source_snapshot.snapshot_sha256,
            "snapshot_size_bytes": source_snapshot.snapshot_size_bytes,
            "immutable_snapshot": True,
        },
    }


def _clean_offline_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize offline benchmark rows and quarantine invalid entries."""
    _validate_offline_dataset_name(payload)
    artifact_dir = Path(_require_str(payload, "artifact_dir"))
    ingest_path = Path(_require_str(payload, "ingest_path"))
    clean_path = artifact_dir / "offline_clean_records.jsonl"
    quarantine_path = artifact_dir / "offline_quarantine_records.jsonl"

    dataset_name = _require_str(payload, "dataset_name")
    dataset_version = _coerce_optional_str(payload.get("dataset_version"))
    normalized_candidates: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    schema_invalid_count = 0
    for row_index, ingest_row in enumerate(_read_jsonl(ingest_path)):
        raw_record = ingest_row.get("raw")
        if not isinstance(raw_record, dict):
            invalid_rows.append(
                {
                    "row_index": row_index,
                    "record_id": ingest_row.get("record_id"),
                    "reason": "raw_record_not_object",
                }
            )
            continue

        normalized = _normalize_offline_dataset_row(
            raw_record=raw_record,
            fallback_record_id=_coerce_optional_str(ingest_row.get("record_id"))
            or f"record-{row_index}",
            dataset_name=dataset_name,
            dataset_version=dataset_version,
        )
        if normalized is None:
            invalid_rows.append(
                {
                    "row_index": row_index,
                    "record_id": ingest_row.get("record_id"),
                    "reason": "missing_required_fields",
                }
            )
            continue

        schema_errors = _validate_offline_clean_row_schema(normalized)
        if schema_errors:
            schema_invalid_count += 1
            invalid_rows.append(
                {
                    "row_index": row_index,
                    "record_id": ingest_row.get("record_id"),
                    "reason": "schema_validation_failed",
                    "schema_version": _OFFLINE_SCHEMA_VERSION,
                    "validation_errors": schema_errors,
                }
            )
            continue

        normalized_candidates.append(
            {
                "row_index": row_index,
                "record_id": _coerce_optional_str(ingest_row.get("record_id")),
                "normalized": normalized,
            }
        )

    dedupe_rows, dedupe_invalid_rows, dedupe_stats = _dedupe_offline_rows(
        normalized_candidates
    )
    clean_rows = dedupe_rows
    invalid_rows.extend(dedupe_invalid_rows)
    clean_rows.sort(key=_offline_clean_row_sort_key)

    _write_jsonl(clean_path, clean_rows)

    quarantine_path_value: str | None = None
    if invalid_rows:
        _write_jsonl(quarantine_path, invalid_rows)
        quarantine_path_value = str(quarantine_path)
    elif quarantine_path.exists():
        quarantine_path.unlink()

    return {
        **payload,
        "stage": "clean",
        "ok": True,
        "clean_path": str(clean_path),
        "quarantine_path": quarantine_path_value,
        "clean_stats": {
            "input_record_count": len(clean_rows) + len(invalid_rows),
            "clean_record_count": len(clean_rows),
            "invalid_record_count": len(invalid_rows),
            "duplicate_instance_id_dropped": dedupe_stats["duplicate_instance_id"],
            "duplicate_content_dropped": dedupe_stats["duplicate_content"],
            "schema_invalid_count": schema_invalid_count,
        },
    }


def _transform_offline_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    """Transform normalized offline rows into canonical dataset instances."""
    _validate_offline_dataset_name(payload)
    artifact_dir = Path(_require_str(payload, "artifact_dir"))
    clean_path = Path(_require_str(payload, "clean_path"))
    transform_path = artifact_dir / "offline_dataset_instances.jsonl"

    dataset_instances: list[dict[str, Any]] = []
    dataset_digest = hashlib.sha1()
    created_at = datetime.now(timezone.utc).isoformat()
    for row in _read_jsonl(clean_path):
        instance = {
            "instance_id": _require_mapping_str(row, "instance_id"),
            "task": _require_mapping_str(row, "task"),
            "repo_id": _require_mapping_str(row, "repo_id"),
            "snapshot_sha": _coerce_optional_str(row.get("snapshot_sha")),
            "failure_type": _coerce_optional_str(row.get("failure_type"))
            or "test_failure",
            "failure_ref": _coerce_optional_str(row.get("failure_ref")),
            "corrected_diff_ref": _require_mapping_str(row, "corrected_diff_ref"),
            "split": _coerce_optional_str(row.get("split")) or "unspecified",
            "dataset_name": _require_mapping_str(row, "dataset_name"),
            "dataset_version": _coerce_optional_str(row.get("dataset_version")),
            "created_at": created_at,
        }
        dataset_instances.append(instance)
        dataset_digest.update(
            f"{instance['instance_id']}|{instance['repo_id']}|"
            f"{instance['corrected_diff_ref']}".encode("utf-8")
        )

    _write_jsonl(transform_path, dataset_instances)
    return {
        **payload,
        "stage": "transform",
        "ok": True,
        "transform_path": str(transform_path),
        "transform_stats": {
            "dataset_instance_count": len(dataset_instances),
            "records_out": len(dataset_instances),
            "dataset_hash": dataset_digest.hexdigest(),
        },
    }


async def _store_offline_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist offline benchmark artifacts and write a run manifest."""
    _validate_offline_dataset_name(payload)
    artifact_dir = Path(_require_str(payload, "artifact_dir"))
    ingest_path = Path(_require_str(payload, "ingest_path"))
    clean_path = Path(_require_str(payload, "clean_path"))
    transform_path = Path(_require_str(payload, "transform_path"))
    dataset_name = _require_str(payload, "dataset_name")
    dataset_version = _coerce_optional_str(payload.get("dataset_version"))
    job_id = _require_str(payload, "job_id")
    workflow_id = _require_str(payload, "workflow_id")
    ingest_stats = payload.get("ingest_stats") or {}
    clean_stats = payload.get("clean_stats") or {}
    transform_stats = payload.get("transform_stats") or {}
    quarantine_path_value = _coerce_optional_str(payload.get("quarantine_path"))
    dataset_instance_writes = _load_dataset_instance_writes(
        transform_path=transform_path,
        workflow_id=workflow_id,
        run_id=job_id,
    )
    dataset_instances_exported = 0
    dataset_instances_export_enabled = bool(settings.postgres_dsn)
    if dataset_instances_export_enabled:
        dataset_instances_exported = await upsert_dataset_instances(
            dataset_instance_writes
        )

    s3_key_prefix = _offline_s3_key_prefix(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        job_id=job_id,
    )
    s3_artifact_keys = _offline_s3_artifact_keys(
        s3_key_prefix=s3_key_prefix,
        artifact_names=[
            "manifest.json",
            "ingest.jsonl",
            "clean.jsonl",
            "dataset_instances.jsonl",
            "quarantine.jsonl",
        ],
    )

    manifest_path = artifact_dir / "offline_manifest.json"
    manifest = {
        "manifest_schema_version": "offline-run-manifest/v1",
        "workflow_type": "OfflineDatasetWorkflow",
        "status": "READY",
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "workflow_id": workflow_id,
        "run_id": job_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "partitions": {
            "dataset": dataset_name,
            "version": dataset_version or "latest",
            "run_id": job_id,
        },
        "metrics": {
            "records_in": ingest_stats.get("records_in"),
            "records_clean": clean_stats.get("clean_record_count"),
            "records_invalid": clean_stats.get("invalid_record_count"),
            "records_out": transform_stats.get("dataset_instance_count"),
        },
        "artifacts": {
            "bronze": {
                "local_path": str(ingest_path),
                "s3_key": s3_artifact_keys.get("ingest.jsonl"),
            },
            "silver": {
                "local_path": str(clean_path),
                "s3_key": s3_artifact_keys.get("clean.jsonl"),
            },
            "gold": {
                "local_path": str(transform_path),
                "s3_key": s3_artifact_keys.get("dataset_instances.jsonl"),
            },
            "quarantine": {
                "local_path": quarantine_path_value,
                "s3_key": s3_artifact_keys.get("quarantine.jsonl"),
            },
            "manifest": {
                "local_path": str(manifest_path),
                "s3_key": s3_artifact_keys.get("manifest.json"),
            },
        },
        "storage": {
            "bucket": settings.s3_bucket,
            "s3_key_prefix": s3_key_prefix,
        },
        "exports": {
            "dataset_instances": {
                "target": "postgres.dataset_instances",
                "enabled": dataset_instances_export_enabled,
                "record_count": dataset_instances_exported,
            }
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    artifacts: dict[str, bytes] = {
        "manifest.json": manifest_path.read_bytes(),
        "ingest.jsonl": ingest_path.read_bytes(),
        "clean.jsonl": clean_path.read_bytes(),
        "dataset_instances.jsonl": transform_path.read_bytes(),
    }
    if quarantine_path_value:
        quarantine_path = Path(quarantine_path_value)
        if quarantine_path.exists():
            artifacts["quarantine.jsonl"] = quarantine_path.read_bytes()

    stored_s3_key_prefix = _maybe_store_offline_artifacts_to_s3(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        job_id=job_id,
        artifacts=artifacts,
    )

    return {
        **payload,
        "stage": "store",
        "ok": True,
        "artifact_manifest_path": str(manifest_path),
        "artifact_dataset_instances_path": str(transform_path),
        "store_stats": {
            "s3_key_prefix": stored_s3_key_prefix,
            "dataset_instances_exported": dataset_instances_exported,
            "dataset_instances_export_enabled": dataset_instances_export_enabled,
        },
    }


def _load_dataset_instance_writes(
    *,
    transform_path: Path,
    workflow_id: str,
    run_id: str,
) -> list[DatasetInstanceWrite]:
    """Read transformed gold rows and map them into Postgres export payloads."""
    writes: list[DatasetInstanceWrite] = []
    for row in _read_jsonl(transform_path):
        writes.append(
            DatasetInstanceWrite(
                dataset_name=_require_mapping_str(row, "dataset_name"),
                dataset_version=_require_mapping_str(row, "dataset_version"),
                instance_id=_require_mapping_str(row, "instance_id"),
                task=_require_mapping_str(row, "task"),
                repo_id=_require_mapping_str(row, "repo_id"),
                snapshot_sha=_coerce_optional_str(row.get("snapshot_sha")),
                failure_type=_coerce_optional_str(row.get("failure_type"))
                or "test_failure",
                failure_ref=_coerce_optional_str(row.get("failure_ref")),
                corrected_diff_ref=_require_mapping_str(row, "corrected_diff_ref"),
                split=_coerce_optional_str(row.get("split")) or "unspecified",
                workflow_id=workflow_id,
                run_id=run_id,
            )
        )
    return writes


def _sanitize_identifier(value: str) -> str:
    """Produce a filesystem-safe identifier segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "unknown"


def _normalize_offline_dataset_name(dataset_name: str) -> str:
    """Normalize offline dataset names for compatibility checks."""
    return re.sub(r"[-_]+", "", dataset_name.strip().lower())


def _validate_offline_dataset_name(payload: dict[str, Any]) -> tuple[str, str]:
    """Validate and normalize supported offline benchmark dataset names."""
    dataset_name = _require_str(payload, "dataset_name")
    dataset_key = _normalize_offline_dataset_name(dataset_name)
    if dataset_key not in _OFFLINE_SUPPORTED_DATASET_KEYS:
        supported = ", ".join(sorted(_OFFLINE_SUPPORTED_DATASETS))
        raise ValueError(
            f"dataset_name '{dataset_name}' is unsupported; expected one of: {supported}"
        )
    return dataset_name, dataset_key


def _coerce_optional_str(value: Any) -> str | None:
    """Coerce optional input values into trimmed strings."""
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, (int, float, bool)):
        normalized = str(value).strip()
        return normalized or None
    return None


def _coerce_text(value: Any) -> str | None:
    """Coerce scalar/collection values into canonical text fields."""
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, (list, dict)):
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True).strip()
        return encoded or None
    return _coerce_optional_str(value)


def _normalize_offline_text(value: str | None) -> str | None:
    """Normalize multiline text fields for deterministic comparison and storage."""
    if value is None:
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    cleaned_lines: list[str] = []
    blank_run = 0
    for line in lines:
        if line:
            cleaned_lines.append(line)
            blank_run = 0
            continue
        blank_run += 1
        if blank_run <= 1:
            cleaned_lines.append("")
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or None


def _normalize_optional_scalar(value: str | None) -> str | None:
    """Normalize optional scalar values for consistent dedupe keys."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_repo_id(value: str | None) -> str | None:
    """Normalize repository identifiers into canonical `owner/repo`-style strings."""
    if value is None:
        return None
    normalized = value.strip()
    if normalized.endswith(".git"):
        normalized = normalized[: -len(".git")]
    lowered = normalized.lower()
    if lowered.startswith("https://github.com/"):
        normalized = normalized[len("https://github.com/") :]
    elif lowered.startswith("http://github.com/"):
        normalized = normalized[len("http://github.com/") :]
    elif lowered.startswith("git@github.com:"):
        normalized = normalized[len("git@github.com:") :]
    normalized = normalized.strip("/")
    return normalized.lower() or None


def _normalize_split(value: str | None) -> str:
    """Normalize dataset split labels to stable lowercase tokens."""
    if value is None:
        return "unspecified"
    normalized = re.sub(r"\s+", "_", value.strip().lower())
    normalized = re.sub(r"[^a-z0-9._-]+", "_", normalized).strip("_")
    return normalized or "unspecified"


def _normalize_failure_type(value: str | None) -> str:
    """Normalize failure type labels to stable lowercase tokens."""
    if value is None:
        return "test_failure"
    normalized = re.sub(r"\s+", "_", value.strip().lower())
    normalized = re.sub(r"[^a-z0-9._-]+", "_", normalized).strip("_")
    return normalized or "test_failure"


def _require_mapping_str(mapping: dict[str, Any], key: str) -> str:
    """Read and validate a required non-empty string field from one mapping."""
    value = _coerce_optional_str(mapping.get(key))
    if value is None:
        raise ValueError(f"mapping field '{key}' is required")
    return value


def _load_swebench_source_snapshot(
    *,
    payload: dict[str, Any],
    dataset_version: str,
) -> SwebenchSnapshot:
    """Load immutable version-pinned SWE-bench records via dedicated adapter."""
    dataset_source_path = _require_str(payload, "dataset_source_path")
    return _SWEBENCH_SNAPSHOT_ADAPTER.load_snapshot(
        dataset_version=dataset_version,
        dataset_source_path=dataset_source_path,
    )


def _validate_offline_clean_row_schema(row: dict[str, Any]) -> list[str]:
    """Validate normalized offline rows against the canonical clean schema."""
    errors: list[str] = []
    required_fields = (
        "instance_id",
        "task",
        "repo_id",
        "corrected_diff_ref",
        "split",
        "failure_type",
        "dataset_name",
        "dataset_version",
    )
    for field in required_fields:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")

    repo_id = _coerce_optional_str(row.get("repo_id"))
    if repo_id is not None and _OFFLINE_REPO_ID_PATTERN.fullmatch(repo_id) is None:
        errors.append("repo_id: expected owner/repo format")

    split = _coerce_optional_str(row.get("split"))
    if split is not None and _OFFLINE_TOKEN_PATTERN.fullmatch(split) is None:
        errors.append("split: expected lowercase token format")

    failure_type = _coerce_optional_str(row.get("failure_type"))
    if (
        failure_type is not None
        and _OFFLINE_TOKEN_PATTERN.fullmatch(failure_type) is None
    ):
        errors.append("failure_type: expected lowercase token format")

    snapshot_sha = _coerce_optional_str(row.get("snapshot_sha"))
    if (
        snapshot_sha is not None
        and _OFFLINE_SNAPSHOT_SHA_PATTERN.fullmatch(snapshot_sha) is None
    ):
        errors.append("snapshot_sha: expected 7-64 lowercase hex characters")

    failure_ref = row.get("failure_ref")
    if failure_ref is not None and not isinstance(failure_ref, str):
        errors.append("failure_ref: expected string or null")

    return errors


def _dedupe_offline_rows(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Apply deterministic dedupe rules and return clean rows + duplicate drops."""
    duplicate_rows: list[dict[str, Any]] = []
    dedupe_stats = {"duplicate_instance_id": 0, "duplicate_content": 0}
    if not candidates:
        return [], duplicate_rows, dedupe_stats

    retained_after_instance: list[dict[str, Any]] = []
    by_instance_id: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        row = candidate["normalized"]
        instance_id = _require_mapping_str(row, "instance_id")
        by_instance_id.setdefault(instance_id, []).append(candidate)

    for instance_id in sorted(by_instance_id):
        winner, losers = _select_canonical_offline_candidate(by_instance_id[instance_id])
        retained_after_instance.append(winner)
        if losers:
            dedupe_stats["duplicate_instance_id"] += len(losers)
            winner_record_id = _coerce_optional_str(winner.get("record_id"))
            for loser in losers:
                duplicate_rows.append(
                    {
                        "row_index": loser.get("row_index"),
                        "record_id": loser.get("record_id"),
                        "reason": "duplicate_instance_id_dropped",
                        "instance_id": instance_id,
                        "winner_record_id": winner_record_id,
                    }
                )

    retained_after_content: list[dict[str, Any]] = []
    by_content_key: dict[str, list[dict[str, Any]]] = {}
    for candidate in retained_after_instance:
        row = candidate["normalized"]
        content_key = _offline_content_fingerprint(row)
        by_content_key.setdefault(content_key, []).append(candidate)

    for content_key in sorted(by_content_key):
        winner, losers = _select_canonical_offline_candidate(by_content_key[content_key])
        retained_after_content.append(winner)
        if losers:
            dedupe_stats["duplicate_content"] += len(losers)
            winner_record_id = _coerce_optional_str(winner.get("record_id"))
            winner_instance_id = _coerce_optional_str(winner["normalized"].get("instance_id"))
            for loser in losers:
                duplicate_rows.append(
                    {
                        "row_index": loser.get("row_index"),
                        "record_id": loser.get("record_id"),
                        "reason": "duplicate_content_signature_dropped",
                        "content_fingerprint": content_key,
                        "winner_record_id": winner_record_id,
                        "winner_instance_id": winner_instance_id,
                    }
                )

    clean_rows = [
        _strip_internal_offline_fields(candidate["normalized"])
        for candidate in retained_after_content
    ]
    return clean_rows, duplicate_rows, dedupe_stats


def _select_canonical_offline_candidate(
    group: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Choose canonical candidate deterministically and return losers."""
    ordered = sorted(group, key=_offline_candidate_sort_key)
    winner = ordered[0]
    return winner, ordered[1:]


def _offline_candidate_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """Deterministic winner ranking for duplicate candidate groups."""
    row = candidate["normalized"]
    instance_source = _coerce_optional_str(row.get("_instance_id_source")) or "fallback"
    explicit_rank = 0 if instance_source == "explicit" else 1
    completeness_score = _offline_candidate_completeness(row)
    corrected_diff_ref = _coerce_optional_str(row.get("corrected_diff_ref")) or ""
    record_id = _coerce_optional_str(candidate.get("record_id")) or ""
    return (
        explicit_rank,
        -completeness_score,
        -len(corrected_diff_ref),
        record_id,
        _coerce_optional_str(row.get("instance_id")) or "",
        _coerce_optional_str(row.get("repo_id")) or "",
        _coerce_optional_str(row.get("snapshot_sha")) or "",
        _offline_content_fingerprint(row),
    )


def _offline_candidate_completeness(row: dict[str, Any]) -> int:
    """Score normalized rows by optional signal density for dedupe ranking."""
    score = 0
    for key in ("snapshot_sha", "failure_ref", "split", "failure_type"):
        if _coerce_optional_str(row.get(key)):
            score += 1
    return score


def _offline_content_fingerprint(row: dict[str, Any]) -> str:
    """Build a stable content-level fingerprint for secondary dedupe."""
    seed = "|".join(
        (
            _require_mapping_str(row, "repo_id"),
            _coerce_optional_str(row.get("snapshot_sha")) or "",
            _require_mapping_str(row, "task"),
            _require_mapping_str(row, "corrected_diff_ref"),
            _coerce_optional_str(row.get("failure_ref")) or "",
            _coerce_optional_str(row.get("split")) or "",
            _require_mapping_str(row, "dataset_name"),
            _coerce_optional_str(row.get("dataset_version")) or "",
        )
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _strip_internal_offline_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Drop internal helper fields before persisting cleaned offline rows."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _offline_clean_row_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Stable ordering for cleaned offline rows written to artifact files."""
    return (
        _coerce_optional_str(row.get("instance_id")) or "",
        _coerce_optional_str(row.get("repo_id")) or "",
        _coerce_optional_str(row.get("snapshot_sha")) or "",
        _coerce_optional_str(row.get("split")) or "",
        _offline_content_fingerprint(row),
    )


def _offline_record_id(
    source_row: dict[str, Any],
    *,
    index: int,
    dataset_name: str,
    dataset_version: str | None,
) -> str:
    """Build deterministic ingest-level record IDs for offline rows."""
    explicit = (
        _coerce_optional_str(source_row.get("instance_id"))
        or _coerce_optional_str(source_row.get("id"))
        or _coerce_optional_str(source_row.get("task_id"))
    )
    if explicit:
        return explicit
    seed = (
        f"{dataset_name}|{dataset_version or 'latest'}|{index}|"
        f"{json.dumps(source_row, ensure_ascii=True, sort_keys=True)}"
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


def _normalize_offline_dataset_row(
    *,
    raw_record: dict[str, Any],
    fallback_record_id: str,
    dataset_name: str,
    dataset_version: str | None,
) -> dict[str, Any] | None:
    """Normalize one raw offline record into canonical benchmark fields."""
    task = _normalize_offline_text(
        _coerce_text(raw_record.get("task"))
        or _coerce_text(raw_record.get("problem_statement"))
        or _coerce_text(raw_record.get("issue_text"))
        or _coerce_text(raw_record.get("prompt"))
    )
    repo_id = _normalize_repo_id(
        _coerce_optional_str(raw_record.get("repo_id"))
        or _coerce_optional_str(raw_record.get("repo"))
        or _coerce_optional_str(raw_record.get("repository"))
    )
    corrected_diff_ref = _normalize_offline_text(
        _coerce_text(raw_record.get("corrected_diff_ref"))
        or _coerce_text(raw_record.get("gold_patch"))
        or _coerce_text(raw_record.get("patch"))
        or _coerce_text(raw_record.get("fix_patch"))
    )
    if task is None or repo_id is None or corrected_diff_ref is None:
        return None

    snapshot_sha = _normalize_optional_scalar(
        _coerce_optional_str(raw_record.get("snapshot_sha"))
        or _coerce_optional_str(raw_record.get("base_commit"))
        or _coerce_optional_str(raw_record.get("commit_sha"))
    )
    failure_type = _normalize_failure_type(
        _coerce_optional_str(raw_record.get("failure_type"))
    )
    failure_ref = _normalize_offline_text(
        _coerce_text(raw_record.get("failure_ref"))
        or _coerce_text(raw_record.get("test_patch"))
        or _coerce_text(raw_record.get("fail_to_pass"))
        or _coerce_text(raw_record.get("FAIL_TO_PASS"))
    )
    split = _normalize_split(
        _coerce_optional_str(raw_record.get("split"))
        or _coerce_optional_str(raw_record.get("subset"))
    )
    explicit_instance_id = _normalize_optional_scalar(
        _coerce_optional_str(raw_record.get("instance_id"))
        or _coerce_optional_str(raw_record.get("id"))
    )
    instance_id = explicit_instance_id or _normalize_optional_scalar(fallback_record_id)
    instance_id_source = "explicit" if explicit_instance_id else "fallback"
    if not instance_id:
        instance_seed = f"{repo_id}|{task}|{snapshot_sha or ''}|{corrected_diff_ref}"
        instance_id = hashlib.sha1(instance_seed.encode("utf-8")).hexdigest()[:20]
        instance_id_source = "generated"

    return {
        "instance_id": instance_id,
        "task": task,
        "repo_id": repo_id,
        "snapshot_sha": snapshot_sha,
        "failure_type": failure_type,
        "failure_ref": failure_ref,
        "corrected_diff_ref": corrected_diff_ref,
        "split": split,
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "_instance_id_source": instance_id_source,
    }


def _load_repo_files(
    *,
    repo_url: str,
    ref: str,
    payload: dict[str, Any],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Load repository source files from GitHub tarball or local path."""
    owner_repo = _GITHUB_CONNECTOR.parse_owner_repo(repo_url)
    token = _resolve_github_token(payload)
    if owner_repo is not None:
        owner, repo = owner_repo
        tarball = _GITHUB_CONNECTOR.fetch_tarball(
            owner=owner,
            repo=repo,
            ref=ref,
            token=token,
        )
        files = _extract_tarball_files(tarball.archive_bytes)
        return tarball.snapshot_sha, files
    local_path = _parse_local_repo_path(repo_url)
    if local_path is None:
        raise ValueError(
            "repo_url must be a GitHub URL/SSH reference or an accessible local path"
        )
    return _load_local_files(local_path=local_path, ref=ref)


def _extract_tarball_files(archive_bytes: bytes) -> list[dict[str, Any]]:
    """Extract, filter, and decode source files from tarball archive bytes."""
    if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"repository archive exceeds max supported size ({_MAX_ARCHIVE_BYTES} bytes)"
        )

    files: list[dict[str, Any]] = []
    total_bytes = 0
    with tarfile.open(fileobj=BytesIO(archive_bytes), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            path = _normalize_archive_path(member.name)
            if not _should_index_path(path):
                continue
            if member.size <= 0 or member.size > _MAX_FILE_BYTES:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read(_MAX_FILE_BYTES + 1)
            if len(raw) > _MAX_FILE_BYTES or _looks_binary(raw):
                continue
            text = raw.decode("utf-8", errors="ignore")
            if not text.strip():
                continue
            encoded_size = len(text.encode("utf-8"))
            if total_bytes + encoded_size > _MAX_TOTAL_TEXT_BYTES:
                break
            files.append(
                {
                    "path": path,
                    "content": text,
                    "size_bytes": encoded_size,
                    "language": _infer_language(path),
                }
            )
            total_bytes += encoded_size
            if len(files) >= _MAX_FILE_COUNT:
                break
    return files


def _normalize_archive_path(path: str) -> str:
    """Strip tarball root directory and normalize path separators."""
    normalized = path.replace("\\", "/").lstrip("./")
    if "/" not in normalized:
        return normalized
    return normalized.split("/", 1)[1]


def _parse_local_repo_path(repo_url: str) -> Path | None:
    """Resolve a local repository path from `repo_url` format."""
    parsed = urlparse(repo_url)
    if parsed.scheme in {"", "file"}:
        candidate = Path(
            parsed.path if parsed.scheme == "file" else repo_url
        ).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _load_local_files(
    local_path: Path, ref: str
) -> tuple[str | None, list[dict[str, Any]]]:
    """Read indexable source files from a local repository checkout."""
    snapshot_sha = _resolve_local_snapshot_sha(local_path, ref)
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for file_path in local_path.rglob("*"):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(local_path).as_posix()
        if not _should_index_path(rel_path):
            continue
        size = file_path.stat().st_size
        if size <= 0 or size > _MAX_FILE_BYTES:
            continue
        raw = file_path.read_bytes()
        if _looks_binary(raw):
            continue
        text = raw.decode("utf-8", errors="ignore")
        if not text.strip():
            continue
        encoded_size = len(text.encode("utf-8"))
        if total_bytes + encoded_size > _MAX_TOTAL_TEXT_BYTES:
            break
        files.append(
            {
                "path": rel_path,
                "content": text,
                "size_bytes": encoded_size,
                "language": _infer_language(rel_path),
            }
        )
        total_bytes += encoded_size
        if len(files) >= _MAX_FILE_COUNT:
            break
    return snapshot_sha, files


def _resolve_local_snapshot_sha(local_path: Path, ref: str) -> str | None:
    """Resolve local git commit SHA for the requested ref when available."""
    try:
        repo = Repo(local_path)
        return repo.commit(ref).hexsha
    except Exception:
        return None


def _resolve_github_token(payload: dict[str, Any]) -> str | None:
    """Resolve optional GitHub token from payload then pipeline settings."""
    payload_token = payload.get("github_token")
    if isinstance(payload_token, str) and payload_token.strip():
        return payload_token.strip()
    if settings.github_read_token is not None:
        configured = settings.github_read_token.get_secret_value().strip()
        if configured:
            return configured
    return None


def _should_index_path(path: str) -> bool:
    """Return true when a repository path should be indexed."""
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    lower_path = normalized.lower()
    for prefix in _SKIP_PREFIXES:
        if lower_path.startswith(prefix.lower()) or f"/{prefix.lower()}" in lower_path:
            return False
    name = Path(normalized).name
    suffix = Path(normalized).suffix.lower()
    return suffix in _SUPPORTED_SUFFIXES or name in _SUPPORTED_FILENAMES


def _looks_binary(raw: bytes) -> bool:
    """Detect binary-like payloads using null-byte heuristics."""
    return b"\x00" in raw[:4096]


def _normalize_source_text(text: str) -> str:
    """Normalize source text while preserving useful formatting boundaries."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]

    cleaned_lines: list[str] = []
    blank_run = 0
    for line in lines:
        if line:
            blank_run = 0
            cleaned_lines.append(line)
            continue
        blank_run += 1
        if blank_run <= 2:
            cleaned_lines.append("")

    cleaned = "\n".join(cleaned_lines).strip()
    if len(cleaned) < 20:
        return ""
    return cleaned


def _chunk_text(
    *,
    content: str,
    chunk_size: int,
    overlap: int,
    min_chunk_size: int,
) -> Iterable[tuple[int, int, int, str]]:
    """Yield overlapping text chunks as `(index, start, end, text)` tuples."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be in [0, chunk_size)")

    cursor = 0
    index = 0
    content_len = len(content)
    while cursor < content_len:
        end = min(content_len, cursor + chunk_size)
        text = content[cursor:end].strip()
        if len(text) >= min_chunk_size:
            yield index, cursor, end, text
            index += 1
        if end >= content_len:
            break
        cursor = end - overlap


def _infer_language(path: str) -> str | None:
    """Map filename suffixes to a coarse language identifier."""
    suffix = Path(path).suffix.lower()
    mappings = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".rs": "rust",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".kt": "kotlin",
        ".swift": "swift",
        ".php": "php",
        ".sql": "sql",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".sh": "shell",
    }
    return mappings.get(suffix)


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """Write newline-delimited JSON records to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Read newline-delimited JSON records from disk."""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _resolve_snapshot_sha(snapshot_sha: Any, *, corpus_hash: Any) -> str:
    """Resolve snapshot SHA, falling back to corpus hash-derived identifier."""
    if isinstance(snapshot_sha, str) and snapshot_sha.strip():
        return snapshot_sha.strip()
    if isinstance(corpus_hash, str) and corpus_hash.strip():
        return f"content-{corpus_hash.strip()[:40]}"
    return "content-unknown"


def _offline_s3_key_prefix(
    *,
    dataset_name: str,
    dataset_version: str | None,
    job_id: str,
) -> str | None:
    """Resolve offline benchmark S3 prefix if bucket storage is configured."""
    bucket = settings.s3_bucket
    if not bucket:
        return None
    return _S3_CONNECTOR.offline_benchmark_prefix(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        job_id=job_id,
    )


def _offline_s3_artifact_keys(
    *,
    s3_key_prefix: str | None,
    artifact_names: Iterable[str],
) -> dict[str, str | None]:
    """Resolve optional S3 keys for offline artifact filenames."""
    result: dict[str, str | None] = {}
    for artifact_name in artifact_names:
        if s3_key_prefix is None:
            result[artifact_name] = None
            continue
        result[artifact_name] = _S3_CONNECTOR.offline_benchmark_artifact_key(
            prefix=s3_key_prefix,
            filename=artifact_name,
        )
    return result


def _maybe_store_runtime_artifacts_to_s3(
    *,
    manifest_path: Path,
    chunks_path: Path,
    repo_id: str,
    ref: str,
    job_id: str,
) -> str | None:
    """Optionally upload runtime artifacts to S3 when bucket config is set."""
    bucket = settings.s3_bucket
    if not bucket:
        return None

    try:
        return _S3_CONNECTOR.upload_runtime_artifacts(
            bucket=bucket,
            repo_id=repo_id,
            ref=ref,
            job_id=job_id,
            manifest_bytes=manifest_path.read_bytes(),
            chunks_bytes=chunks_path.read_bytes(),
        )
    except Exception:
        return None


def _maybe_store_offline_artifacts_to_s3(
    *,
    dataset_name: str,
    dataset_version: str | None,
    job_id: str,
    artifacts: dict[str, bytes],
) -> str | None:
    """Optionally upload offline benchmark artifacts to S3 when configured."""
    bucket = settings.s3_bucket
    if not bucket:
        return None

    try:
        return _S3_CONNECTOR.upload_offline_benchmark_artifacts(
            bucket=bucket,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            job_id=job_id,
            artifacts=artifacts,
        )
    except Exception:
        return None
