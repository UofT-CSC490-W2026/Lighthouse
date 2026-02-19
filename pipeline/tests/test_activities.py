"""Unit tests for pipeline Temporal activity functions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src import activities


def _run(coro):
    """Execute one async coroutine inside a fresh event loop."""
    return asyncio.run(coro)


def _runtime_payload() -> dict[str, object]:
    """Build a minimal runtime payload used by activity unit tests."""
    return {
        "job_id": "job_001",
        "workflow_id": "runtime-index:octo/repo:main",
        "repo_id": "octo/repo",
        "repo_url": "https://github.com/octo/repo",
        "ref": "main",
        "force_reindex": False,
    }


def _offline_payload() -> dict[str, object]:
    """Build a minimal offline benchmark payload used by activity tests."""
    return {
        "job_id": "job_offline_001",
        "workflow_id": "offline-datasets:swebench:v1",
        "dataset_name": "swebench",
        "dataset_version": "v1",
    }


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """Write JSONL fixture records for activity stage input files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def test_ingest_activity_happy_path(tmp_path: Path) -> None:
    """`ingest_activity` should write source rows and return metadata."""
    payload = _runtime_payload()
    source_files = [
        {
            "path": "src/app.py",
            "content": "print('hello')\n",
            "size_bytes": 15,
            "language": "python",
        }
    ]
    with (
        patch.object(activities, "_log_activity_info"),
        patch.object(activities, "_runtime_artifact_dir", return_value=tmp_path),
        patch.object(
            activities, "_load_repo_files", return_value=("abc123", source_files)
        ),
    ):
        result = _run(activities.ingest_activity(payload))

    assert result["stage"] == "ingest"
    assert result["snapshot_sha"] == "abc123"
    assert result["ingest_stats"]["file_count"] == 1
    assert Path(result["ingest_path"]).exists()


def test_ingest_activity_validation_failure() -> None:
    """`ingest_activity` should reject empty required runtime fields."""
    payload = _runtime_payload()
    payload["repo_url"] = " "
    with (
        patch.object(activities, "_log_activity_info"),
        pytest.raises(ValueError, match="repo_url"),
    ):
        _run(activities.ingest_activity(payload))


def test_offline_activity_flow_happy_path(tmp_path: Path) -> None:
    """Offline ingest/clean/transform/store should process benchmark rows."""
    payload = {
        **_offline_payload(),
        "dataset_records": [
            {
                "instance_id": "swe-1",
                "repo": "octo/repo",
                "problem_statement": "Fix parser edge-case regression",
                "base_commit": "abc123",
                "patch": "diff --git a/app.py b/app.py",
                "test_patch": "FAIL_TO_PASS=test_parser",
                "split": "test",
            },
            {
                "instance_id": "swe-1",
                "repo": "octo/repo",
                "problem_statement": "duplicate row",
                "patch": "diff --git a/app.py b/app.py",
            },
            {
                "instance_id": "swe-3",
                "problem_statement": "missing repo should be quarantined",
                "patch": "diff --git a/app.py b/app.py",
            },
        ],
    }
    with (
        patch.object(activities, "_log_activity_info"),
        patch.object(activities, "_offline_artifact_dir", return_value=tmp_path),
        patch.object(
            activities,
            "_maybe_store_offline_artifacts_to_s3",
            return_value="offline-datasets/benchmark/swebench/v1/job_offline_001",
        ),
    ):
        ingest_result = _run(activities.ingest_activity(payload))
        clean_result = _run(activities.clean_activity(ingest_result))
        transform_result = _run(activities.transform_activity(clean_result))
        store_result = _run(activities.store_activity(transform_result))

    assert ingest_result["stage"] == "ingest"
    assert ingest_result["ingest_stats"]["records_in"] == 3
    assert Path(ingest_result["ingest_path"]).exists()

    assert clean_result["stage"] == "clean"
    assert clean_result["clean_stats"]["clean_record_count"] == 1
    assert clean_result["clean_stats"]["invalid_record_count"] == 2
    assert Path(clean_result["clean_path"]).exists()
    assert Path(clean_result["quarantine_path"]).exists()

    assert transform_result["stage"] == "transform"
    assert transform_result["transform_stats"]["dataset_instance_count"] == 1
    assert Path(transform_result["transform_path"]).exists()

    assert store_result["stage"] == "store"
    assert store_result["store_stats"]["s3_key_prefix"] is not None
    manifest_path = Path(store_result["artifact_manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset_name"] == "swebench"
    assert manifest["dataset_version"] == "v1"


def test_offline_ingest_validation_failure() -> None:
    """Offline ingest should reject unsupported dataset names."""
    payload = {
        **_offline_payload(),
        "dataset_name": "unknown-benchmark",
        "dataset_records": [
            {
                "instance_id": "a1",
                "repo": "octo/repo",
                "problem_statement": "sample",
                "patch": "diff --git a/a b/a",
            }
        ],
    }
    with (
        patch.object(activities, "_log_activity_info"),
        pytest.raises(ValueError, match="unsupported"),
    ):
        _run(activities.ingest_activity(payload))


def test_clean_activity_happy_path(tmp_path: Path) -> None:
    """`clean_activity` should normalize and deduplicate ingest rows."""
    ingest_path = tmp_path / "ingest_files.jsonl"
    _write_jsonl(
        ingest_path,
        [
            {
                "path": "src/a.py",
                "content": "def alpha():\n    return 123\n\n\n\n",
                "size_bytes": 30,
            },
            {"path": "src/a.py", "content": "duplicate\n", "size_bytes": 10},
            {"path": "src/b.py", "content": "   \n", "size_bytes": 4},
        ],
    )
    payload = {
        **_runtime_payload(),
        "artifact_dir": str(tmp_path),
        "ingest_path": str(ingest_path),
    }
    with patch.object(activities, "_log_activity_info"):
        result = _run(activities.clean_activity(payload))

    assert result["stage"] == "clean"
    assert result["clean_stats"]["document_count"] == 1
    assert result["clean_stats"]["dropped_records"] == 2
    assert Path(result["clean_path"]).exists()


def test_clean_activity_validation_failure(tmp_path: Path) -> None:
    """`clean_activity` should fail when required path fields are missing."""
    payload = {
        **_runtime_payload(),
        "artifact_dir": str(tmp_path),
        "ingest_path": "",
    }
    with (
        patch.object(activities, "_log_activity_info"),
        pytest.raises(ValueError, match="ingest_path"),
    ):
        _run(activities.clean_activity(payload))


def test_transform_activity_happy_path(tmp_path: Path) -> None:
    """`transform_activity` should chunk documents and emit corpus stats."""
    clean_path = tmp_path / "clean_documents.jsonl"
    _write_jsonl(
        clean_path,
        [
            {
                "path": "src/a.py",
                "content": "line\n" * 500,
                "size_bytes": 2500,
                "line_count": 500,
                "language": "python",
            }
        ],
    )
    payload = {
        **_runtime_payload(),
        "artifact_dir": str(tmp_path),
        "clean_path": str(clean_path),
    }
    with patch.object(activities, "_log_activity_info"):
        result = _run(activities.transform_activity(payload))

    assert result["stage"] == "transform"
    assert result["transform_stats"]["chunk_count"] > 0
    assert Path(result["transform_path"]).exists()


def test_transform_activity_validation_failure(tmp_path: Path) -> None:
    """`transform_activity` should fail when clean path is missing/invalid."""
    payload = {
        **_runtime_payload(),
        "artifact_dir": str(tmp_path),
        "clean_path": "",
    }
    with (
        patch.object(activities, "_log_activity_info"),
        pytest.raises(ValueError, match="clean_path"),
    ):
        _run(activities.transform_activity(payload))


def test_store_activity_happy_path(tmp_path: Path) -> None:
    """`store_activity` should write manifest and resolve snapshot sha."""
    transform_path = tmp_path / "transform_chunks.jsonl"
    _write_jsonl(
        transform_path,
        [
            {
                "chunk_id": "chunk_1",
                "repo_id": "octo/repo",
                "ref": "main",
                "path": "src/a.py",
                "chunk_index": 0,
                "start_char": 0,
                "end_char": 100,
                "text": "hello",
                "text_hash": "h1",
            }
        ],
    )
    payload = {
        **_runtime_payload(),
        "artifact_dir": str(tmp_path),
        "transform_path": str(transform_path),
        "transform_stats": {"corpus_hash": "cafebabe"},
        "ingest_stats": {"file_count": 1, "total_text_bytes": 12},
        "clean_stats": {"document_count": 1, "dropped_records": 0},
    }
    with (
        patch.object(activities, "_log_activity_info"),
        patch.object(
            activities, "_maybe_store_runtime_artifacts_to_s3", return_value=None
        ),
    ):
        result = _run(activities.store_activity(payload))

    assert result["stage"] == "store"
    assert result["snapshot_sha"] == "content-cafebabe"
    assert Path(result["artifact_manifest_path"]).exists()


def test_store_activity_validation_failure(tmp_path: Path) -> None:
    """`store_activity` should fail on missing required transform path field."""
    payload = {
        **_runtime_payload(),
        "artifact_dir": str(tmp_path),
        "transform_path": "",
    }
    with (
        patch.object(activities, "_log_activity_info"),
        pytest.raises(ValueError, match="transform_path"),
    ):
        _run(activities.store_activity(payload))


def test_mental_model_activity_happy_path() -> None:
    """`mental_model_activity` returns a success envelope as placeholder."""
    payload = {"repo_id": "octo/repo"}
    with patch.object(activities, "_log_activity_info"):
        result = _run(activities.mental_model_activity(payload))
    assert result["stage"] == "mental_model"
    assert result["ok"] is True


def test_persist_start_activity_happy_path() -> None:
    """Persist-start activity should call persistence service with expected args."""
    payload = _runtime_payload()
    with (
        patch.object(activities, "_log_activity_info"),
        patch.object(
            activities,
            "record_runtime_index_started",
            new=AsyncMock(),
        ) as mock_record,
    ):
        result = _run(activities.persist_runtime_index_start_activity(payload))

    assert result["stage"] == "persist_start"
    mock_record.assert_awaited_once()


def test_persist_success_activity_happy_path() -> None:
    """Persist-success activity should record READY terminal state."""
    payload = {**_runtime_payload(), "snapshot_sha": "abc123"}
    with (
        patch.object(activities, "_log_activity_info"),
        patch.object(
            activities,
            "record_runtime_index_ready",
            new=AsyncMock(),
        ) as mock_record,
    ):
        result = _run(activities.persist_runtime_index_success_activity(payload))

    assert result["stage"] == "persist_success"
    mock_record.assert_awaited_once()


def test_persist_failure_activity_happy_path() -> None:
    """Persist-failure activity should record FAILED state/error metadata."""
    payload = {
        **_runtime_payload(),
        "stage": "CLEAN",
        "progress_pct": 42,
        "error_code": "RUNTIME_INDEX_TERMINAL_VALIDATION",
        "error_message": "bad input",
    }
    with (
        patch.object(activities, "_log_activity_info"),
        patch.object(
            activities,
            "record_runtime_index_failed",
            new=AsyncMock(),
        ) as mock_record,
    ):
        result = _run(activities.persist_runtime_index_failure_activity(payload))

    assert result["stage"] == "persist_failure"
    mock_record.assert_awaited_once()


def test_persist_progress_activity_happy_path() -> None:
    """Persist-progress activity should record stage/progress updates."""
    payload = {**_runtime_payload(), "stage": "TRANSFORM", "progress_pct": 70}
    with (
        patch.object(activities, "_log_activity_info"),
        patch.object(
            activities,
            "record_runtime_index_progress",
            new=AsyncMock(),
        ) as mock_record,
    ):
        result = _run(activities.persist_runtime_index_progress_activity(payload))

    assert result["stage"] == "persist_progress"
    assert result["progress_pct"] == 70
    mock_record.assert_awaited_once()


def test_persist_progress_activity_validation_failure() -> None:
    """Persist-progress activity should validate percentage bounds."""
    payload = {**_runtime_payload(), "stage": "TRANSFORM", "progress_pct": 101}
    with (
        patch.object(activities, "_log_activity_info"),
        pytest.raises(ValueError, match="progress_pct"),
    ):
        _run(activities.persist_runtime_index_progress_activity(payload))
