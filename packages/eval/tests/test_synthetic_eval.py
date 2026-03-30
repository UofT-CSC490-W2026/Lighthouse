from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from eval.synthetic import prepare_synthetic_workspace
from eval.synthetic.eval import (
    evaluate_synthetic_predictions,
    summarize_synthetic_run,
    validate_prepared_synthetic_workspace,
)
from eval.synthetic.predictions import SyntheticPredictionRecord


@pytest.mark.integration
def test_validate_prepared_synthetic_workspace_accepts_buggy_then_gold_fixed_tasks(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=2,
        seed=13,
        workspace_root=tmp_path,
    )

    results = validate_prepared_synthetic_workspace(workspace)

    assert len(results) == 2
    assert all(result.buggy_tests_failed for result in results)
    assert all(result.gold_patch_applied for result in results)
    assert all(result.repaired_tests_passed for result in results)
    assert workspace.validation_report_path.is_file()


@pytest.mark.integration
def test_evaluate_synthetic_predictions_resolves_task_with_gold_patch(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=1,
        seed=5,
        workspace_root=tmp_path / "workspace",
    )
    prepared = workspace.tasks[0]
    predictions_path = tmp_path / "predictions.jsonl"
    record = SyntheticPredictionRecord(
        task_id=prepared.task.task_id,
        task_type=prepared.task.task_type,
        model_name_or_path="bedrock/test-model",
        context_source="baseline",
        model_patch=prepared.task.gold_patch_path.read_text(encoding="utf-8"),
        full_output=prepared.task.gold_patch_path.read_text(encoding="utf-8"),
    )
    _write_predictions(predictions_path, [record])

    summary = evaluate_synthetic_predictions(
        workspace=workspace,
        predictions_path=predictions_path,
        run_id="synthetic-gold-pass",
        runs_root=tmp_path / "runs",
    )

    assert summary.total_instances == 1
    assert summary.submitted_instances == 1
    assert summary.completed_instances == 1
    assert summary.resolved_instances == 1
    assert summary.unresolved_instances == 0
    assert summary.empty_patch_instances == 0
    assert summary.error_instances == 0
    assert summary.results[0].patch_applied is True
    assert summary.results[0].tests_passed is True
    assert summary.instances[0].status == "resolved"
    assert summary.instances[0].fail_to_pass_successes == prepared.task.pytest_targets
    assert (summary.run_dir / "summary.json").is_file()


@pytest.mark.integration
def test_evaluate_synthetic_predictions_normalizes_synthetic_repo_prefixes(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=1,
        seed=5,
        workspace_root=tmp_path / "workspace",
    )
    prepared = workspace.tasks[0]
    predictions_path = tmp_path / "predictions-prefixed.jsonl"
    gold_patch = prepared.task.gold_patch_path.read_text(encoding="utf-8")
    prefixed_patch = gold_patch.replace(
        "a/consumer_app/",
        f"a/{prepared.task.repo_a_name}/consumer_app/",
    ).replace(
        "b/consumer_app/",
        f"b/{prepared.task.repo_a_name}/consumer_app/",
    )
    record = SyntheticPredictionRecord(
        task_id=prepared.task.task_id,
        task_type=prepared.task.task_type,
        model_name_or_path="bedrock/test-model",
        context_source="code",
        model_patch=prefixed_patch,
        full_output=prefixed_patch,
    )
    _write_predictions(predictions_path, [record])

    summary = evaluate_synthetic_predictions(
        workspace=workspace,
        predictions_path=predictions_path,
        run_id="synthetic-prefixed-pass",
        runs_root=tmp_path / "runs",
    )

    assert summary.results[0].patch_applied is True
    assert summary.results[0].tests_passed is True


@pytest.mark.integration
def test_summarize_synthetic_run_reports_unresolved_empty_patch(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=1,
        seed=5,
        workspace_root=tmp_path / "workspace",
    )
    prepared = workspace.tasks[0]
    predictions_path = tmp_path / "predictions.jsonl"
    record = SyntheticPredictionRecord(
        task_id=prepared.task.task_id,
        task_type=prepared.task.task_type,
        model_name_or_path="bedrock/test-model",
        context_source="wiki",
        model_patch="",
        full_output="",
    )
    _write_predictions(predictions_path, [record])

    evaluate_synthetic_predictions(
        workspace=workspace,
        predictions_path=predictions_path,
        run_id="synthetic-empty-patch",
        runs_root=tmp_path / "runs",
    )
    summary = summarize_synthetic_run(
        run_id="synthetic-empty-patch",
        runs_root=tmp_path / "runs",
    )

    assert summary.total_instances == 1
    assert summary.submitted_instances == 1
    assert summary.resolved_instances == 0
    assert summary.empty_patch_instances == 1
    assert summary.error_instances == 0
    assert summary.patch_apply_failures == 0
    assert summary.results[0].context_source == "wiki"
    assert summary.results[0].failing_tests == prepared.task.pytest_targets
    assert summary.instances[0].status == "missing_patch"


@pytest.mark.integration
def test_validate_single_repo_wrong_operator_family(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        family_name="synthetic-wrong-operator",
        task_count=2,
        seed=13,
        workspace_root=tmp_path,
    )

    results = validate_prepared_synthetic_workspace(workspace)

    assert len(results) == 2
    assert all(result.buggy_tests_failed for result in results)
    assert all(result.gold_patch_applied for result in results)
    assert all(result.repaired_tests_passed for result in results)


@pytest.mark.integration
def test_validate_dual_repo_doc_behavior_family(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        family_name="synthetic-doc-behavior",
        task_count=2,
        seed=13,
        workspace_root=tmp_path,
    )

    results = validate_prepared_synthetic_workspace(workspace)

    assert len(results) == 2
    assert all(result.buggy_tests_failed for result in results)
    assert all(result.gold_patch_applied for result in results)
    assert all(result.repaired_tests_passed for result in results)


@pytest.mark.integration
def test_evaluate_single_repo_predictions_resolves_with_gold(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        family_name="synthetic-wrong-operator",
        task_count=1,
        seed=5,
        workspace_root=tmp_path / "workspace",
    )
    prepared = workspace.tasks[0]
    predictions_path = tmp_path / "predictions.jsonl"
    record = SyntheticPredictionRecord(
        task_id=prepared.task.task_id,
        task_type=prepared.task.task_type,
        model_name_or_path="bedrock/test-model",
        context_source="baseline",
        model_patch=prepared.task.gold_patch_path.read_text(encoding="utf-8"),
        full_output=prepared.task.gold_patch_path.read_text(encoding="utf-8"),
    )
    _write_predictions(predictions_path, [record])

    summary = evaluate_synthetic_predictions(
        workspace=workspace,
        predictions_path=predictions_path,
        run_id="single-repo-gold-pass",
        runs_root=tmp_path / "runs",
    )

    assert summary.resolved_instances == 1
    assert summary.results[0].patch_applied is True
    assert summary.results[0].tests_passed is True


def _write_predictions(path: Path, records: list[SyntheticPredictionRecord]) -> None:
    path.write_text(
        "\n".join(json.dumps(asdict(record)) for record in records) + "\n",
        encoding="utf-8",
    )
