"""Unit tests for offline source adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.offline_sources import SwebenchSnapshotAdapter


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """Write JSONL fixture records to disk for adapter tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def test_swebench_adapter_happy_path(tmp_path: Path) -> None:
    """Adapter should load one version-pinned SWE-bench JSONL snapshot."""
    adapter = SwebenchSnapshotAdapter()
    source_path = tmp_path / "swebench-v1.jsonl"
    _write_jsonl(
        source_path,
        [
            {
                "instance_id": "swe-1",
                "repo": "octo/repo",
                "problem_statement": "sample task",
                "patch": "diff --git a/a b/a",
                "dataset_version": "v1",
            }
        ],
    )

    snapshot = adapter.load_snapshot(
        dataset_version="v1",
        dataset_source_path=str(source_path),
    )

    assert snapshot.dataset_version == "v1"
    assert snapshot.source_format == "jsonl"
    assert snapshot.snapshot_size_bytes > 0
    assert len(snapshot.records) == 1


def test_swebench_adapter_rejects_mismatched_record_version(tmp_path: Path) -> None:
    """Adapter should reject snapshots containing conflicting version fields."""
    adapter = SwebenchSnapshotAdapter()
    source_path = tmp_path / "swebench-v1.jsonl"
    _write_jsonl(
        source_path,
        [
            {
                "instance_id": "swe-1",
                "repo": "octo/repo",
                "problem_statement": "sample task",
                "patch": "diff --git a/a b/a",
                "dataset_version": "v2",
            }
        ],
    )

    with pytest.raises(ValueError, match="mismatched"):
        adapter.load_snapshot(
            dataset_version="v1",
            dataset_source_path=str(source_path),
        )


def test_swebench_adapter_requires_version_hint_in_file_path(tmp_path: Path) -> None:
    """Adapter should enforce version hints in source file paths."""
    adapter = SwebenchSnapshotAdapter()
    source_path = tmp_path / "instances.jsonl"
    _write_jsonl(
        source_path,
        [
            {
                "instance_id": "swe-1",
                "repo": "octo/repo",
                "problem_statement": "sample task",
                "patch": "diff --git a/a b/a",
            }
        ],
    )

    with pytest.raises(ValueError, match="must encode dataset_version"):
        adapter.load_snapshot(
            dataset_version="v1",
            dataset_source_path=str(source_path),
        )
