from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

import pytest

from eval.synthetic.compare import compare_synthetic_runs, render_synthetic_comparison_tables
from eval.synthetic.eval import list_synthetic_run_ids


@pytest.mark.unit
def test_compare_synthetic_runs_classifies_improvement_and_regression(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    _write_summary(
        runs_root / "baseline-run" / "summary.json",
        {
            "family_name": "synthetic-ab-contracts",
            "family_version": "1",
            "run_id": "baseline-run",
            "run_dir": str((runs_root / "baseline-run").resolve()),
            "predictions_path": "baseline.jsonl",
            "total_tasks": 2,
            "resolved_tasks": 0,
            "unresolved_tasks": 2,
            "patch_apply_failures": 1,
            "error_tasks": 1,
            "results": [
                {
                    "task_id": "task-1",
                    "task_type": "api_contract_mismatch",
                    "model_name_or_path": "bedrock/test",
                    "context_source": "baseline",
                    "patch_applied": True,
                    "tests_passed": False,
                    "resolved": False,
                    "failing_tests": ["test_one"],
                    "pytest_targets": ["test_one"],
                    "return_code": 1,
                    "patch_apply_error": None,
                    "repo_a_path": "repo_a",
                    "repo_b_path": "repo_b",
                },
                {
                    "task_id": "task-2",
                    "task_type": "api_contract_mismatch",
                    "model_name_or_path": "bedrock/test",
                    "context_source": "baseline",
                    "patch_applied": False,
                    "tests_passed": False,
                    "resolved": False,
                    "failing_tests": ["test_two"],
                    "pytest_targets": ["test_two"],
                    "return_code": 1,
                    "patch_apply_error": "patch failed",
                    "repo_a_path": "repo_a",
                    "repo_b_path": "repo_b",
                },
            ],
        },
    )
    _write_summary(
        runs_root / "lighthouse-run" / "summary.json",
        {
            "family_name": "synthetic-ab-contracts",
            "family_version": "1",
            "run_id": "lighthouse-run",
            "run_dir": str((runs_root / "lighthouse-run").resolve()),
            "predictions_path": "lighthouse.jsonl",
            "total_tasks": 2,
            "resolved_tasks": 1,
            "unresolved_tasks": 1,
            "patch_apply_failures": 0,
            "error_tasks": 0,
            "results": [
                {
                    "task_id": "task-1",
                    "task_type": "api_contract_mismatch",
                    "model_name_or_path": "bedrock/test",
                    "context_source": "code",
                    "patch_applied": True,
                    "tests_passed": True,
                    "resolved": True,
                    "failing_tests": [],
                    "pytest_targets": ["test_one"],
                    "return_code": 0,
                    "patch_apply_error": None,
                    "repo_a_path": "repo_a",
                    "repo_b_path": "repo_b",
                },
                {
                    "task_id": "task-2",
                    "task_type": "api_contract_mismatch",
                    "model_name_or_path": "bedrock/test",
                    "context_source": "code",
                    "patch_applied": True,
                    "tests_passed": False,
                    "resolved": False,
                    "failing_tests": ["test_two", "test_three"],
                    "pytest_targets": ["test_two"],
                    "return_code": 1,
                    "patch_apply_error": None,
                    "repo_a_path": "repo_a",
                    "repo_b_path": "repo_b",
                },
            ],
        },
    )

    comparison = compare_synthetic_runs(
        baseline_run_id="baseline-run",
        lighthouse_run_id="lighthouse-run",
        runs_root=runs_root,
    )

    assert comparison.improved_tasks == 1
    assert comparison.regressed_tasks == 1
    assert comparison.unchanged_tasks == 0
    assert comparison.task_comparisons[0].delta == "improved"
    assert comparison.task_comparisons[1].delta == "regressed"


@pytest.mark.unit
def test_render_synthetic_comparison_tables_includes_overall_and_per_task_tables(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    summary_payload = {
        "family_name": "synthetic-ab-contracts",
        "family_version": "1",
        "run_id": "run-a",
        "run_dir": str((runs_root / "run-a").resolve()),
        "predictions_path": "run-a.jsonl",
        "total_tasks": 1,
        "resolved_tasks": 0,
        "unresolved_tasks": 1,
        "patch_apply_failures": 0,
        "error_tasks": 0,
        "results": [
            {
                "task_id": "task-1",
                "task_type": "api_contract_mismatch",
                "model_name_or_path": "bedrock/test",
                "context_source": "baseline",
                "patch_applied": True,
                "tests_passed": False,
                "resolved": False,
                "failing_tests": ["test_one"],
                "pytest_targets": ["test_one"],
                "return_code": 1,
                "patch_apply_error": None,
                "repo_a_path": "repo_a",
                "repo_b_path": "repo_b",
            }
        ],
    }
    _write_summary(runs_root / "run-a" / "summary.json", summary_payload)
    summary_payload = {
        **summary_payload,
        "run_id": "run-b",
        "run_dir": str((runs_root / "run-b").resolve()),
        "predictions_path": "run-b.jsonl",
        "results": [
            {
                **summary_payload["results"][0],
                "context_source": "code",
                "resolved": True,
                "tests_passed": True,
                "failing_tests": [],
                "return_code": 0,
            }
        ],
        "resolved_tasks": 1,
        "unresolved_tasks": 0,
    }
    _write_summary(runs_root / "run-b" / "summary.json", summary_payload)

    comparison = compare_synthetic_runs(
        baseline_run_id="run-a",
        lighthouse_run_id="run-b",
        runs_root=runs_root,
        baseline_label="base",
        lighthouse_label="lh",
    )
    text = render_synthetic_comparison_tables(comparison)

    assert "Overall" in text
    assert "Per-task" in text
    assert "base" in text
    assert "lh" in text
    assert "task-1" in text
    assert "improved" in text
    assert "submitted_instances" in text
    assert "empty_patch_instances" in text
    assert "Base config:" in text
    assert "base.patch_exists" in text
    assert "base.FAIL_TO_PASS.failure" in text


@pytest.mark.unit
def test_list_synthetic_run_ids_discovers_summary_directories(tmp_path) -> None:
    _write_summary(
        tmp_path / "run-one" / "summary.json",
        {
            "family_name": "synthetic-ab-contracts",
            "family_version": "1",
            "run_id": "run-one",
            "run_dir": str((tmp_path / "run-one").resolve()),
            "predictions_path": "run-one.jsonl",
            "total_tasks": 0,
            "resolved_tasks": 0,
            "unresolved_tasks": 0,
            "patch_apply_failures": 0,
            "error_tasks": 0,
            "results": [],
        },
    )
    (tmp_path / "not-a-run").mkdir(parents=True, exist_ok=True)

    assert list_synthetic_run_ids(runs_root=tmp_path) == ("run-one",)


def _write_summary(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
