"""Unit tests for offline source adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.offline_sources import RollingIssuePrDiffAdapter, SwebenchSnapshotAdapter


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


def test_rolling_issue_pr_diff_adapter_applies_watermark_and_dedupe(
    tmp_path: Path,
) -> None:
    """Rolling adapter should bound records by watermark and keep latest chain rows."""
    adapter = RollingIssuePrDiffAdapter()
    source_path = tmp_path / "issue_pr_diff.jsonl"
    _write_jsonl(
        source_path,
        [
            {
                "repository_full_name": "octo/repo",
                "issue_number": 10,
                "pr_number": 20,
                "issue_title": "old",
                "merge_patch": "diff --git a/a.py b/a.py",
                "merged_at": "2026-02-01T00:00:00Z",
                "dataset_version": "rolling-live",
            },
            {
                "repository_full_name": "octo/repo",
                "issue_number": 10,
                "pr_number": 20,
                "issue_title": "new",
                "merge_patch": "diff --git a/a.py b/a.py",
                "merged_at": "2026-02-01T12:00:00Z",
                "dataset_version": "rolling-live",
            },
            {
                "repository_full_name": "octo/repo",
                "issue_number": 11,
                "pr_number": 21,
                "issue_title": "outside window",
                "merge_patch": "diff --git a/b.py b/b.py",
                "merged_at": "2026-01-01T00:00:00Z",
                "dataset_version": "rolling-live",
            },
        ],
    )

    snapshot = adapter.load_snapshot(
        dataset_version="rolling-live",
        dataset_source_path=str(source_path),
        watermark_start="2026-02-01T00:00:00Z",
        watermark_end="2026-02-02T00:00:00Z",
    )

    assert snapshot.raw_record_count == 3
    assert snapshot.filtered_record_count == 1
    assert snapshot.watermark_start is not None
    assert snapshot.watermark_end is not None
    assert snapshot.records[0]["issue_title"] == "new"


def test_rolling_issue_pr_diff_adapter_rejects_invalid_bounds(tmp_path: Path) -> None:
    """Rolling adapter should reject invalid watermark ordering."""
    adapter = RollingIssuePrDiffAdapter()
    source_path = tmp_path / "issue_pr_diff.jsonl"
    _write_jsonl(
        source_path,
        [
            {
                "repository_full_name": "octo/repo",
                "issue_number": 10,
                "pr_number": 20,
                "issue_title": "sample",
                "merge_patch": "diff --git a/a.py b/a.py",
                "merged_at": "2026-02-01T00:00:00Z",
                "dataset_version": "rolling-live",
            }
        ],
    )

    with pytest.raises(ValueError, match="watermark_start must be <= watermark_end"):
        adapter.load_snapshot(
            dataset_version="rolling-live",
            dataset_source_path=str(source_path),
            watermark_start="2026-02-02T00:00:00Z",
            watermark_end="2026-02-01T00:00:00Z",
        )
