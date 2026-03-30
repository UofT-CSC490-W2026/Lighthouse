from __future__ import annotations

from collections.abc import Mapping
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from .metadata import (
    SyntheticExperimentMetadata,
    empty_synthetic_experiment_metadata,
    synthetic_experiment_metadata_from_json,
)
from eval.efficiency import (
    GenerationCallMetrics,
    GenerationAggregateMetrics,
    RunEfficiencySummary,
    aggregate_generation_metrics,
)
from .predictions import SyntheticPredictionRecord, load_synthetic_predictions
from .workspace import (
    DEFAULT_SYNTHETIC_RUNS_ROOT,
    PreparedSyntheticWorkspace,
    copy_prepared_task_repositories,
    write_validation_report,
)

_FAILED_TEST_PREFIXES = ("FAILED ", "ERROR ")


@dataclass(frozen=True)
class SyntheticValidationResult:
    task_id: str
    task_type: str
    buggy_tests_failed: bool
    gold_patch_applied: bool
    repaired_tests_passed: bool
    failing_tests_before_patch: tuple[str, ...]
    failing_tests_after_patch: tuple[str, ...]


@dataclass(frozen=True)
class SyntheticTaskEvaluationResult:
    task_id: str
    task_type: str
    model_name_or_path: str
    context_source: str
    prediction_present: bool
    patch_exists: bool
    patch_applied: bool
    tests_passed: bool
    resolved: bool
    failing_tests: tuple[str, ...]
    pytest_targets: tuple[str, ...]
    return_code: int
    patch_apply_error: str | None
    stdout: str
    stderr: str
    repo_a_path: Path
    repo_b_path: Path | None


@dataclass(frozen=True)
class SyntheticInstanceSummary:
    task_id: str
    task_type: str
    model_name_or_path: str
    context_source: str
    prediction_present: bool
    resolved: bool
    patch_exists: bool
    patch_successfully_applied: bool
    fail_to_pass_successes: tuple[str, ...]
    fail_to_pass_failures: tuple[str, ...]
    pass_to_pass_failures: tuple[str, ...]
    patch_apply_error: str | None

    @property
    def status(self) -> str:
        if self.resolved:
            return "resolved"
        if not self.prediction_present:
            return "error"
        if not self.patch_exists:
            return "missing_patch"
        if not self.patch_successfully_applied:
            return "patch_failed"
        return "unresolved"


@dataclass(frozen=True)
class SyntheticRunSummary:
    family_name: str
    family_version: str
    run_id: str
    run_dir: Path
    predictions_path: Path
    experiment: SyntheticExperimentMetadata
    total_instances: int
    submitted_instances: int
    completed_instances: int
    resolved_instances: int
    unresolved_instances: int
    empty_patch_instances: int
    error_instances: int
    submitted_ids: tuple[str, ...]
    completed_ids: tuple[str, ...]
    resolved_ids: tuple[str, ...]
    unresolved_ids: tuple[str, ...]
    empty_patch_ids: tuple[str, ...]
    error_ids: tuple[str, ...]
    instances: tuple[SyntheticInstanceSummary, ...]
    results: tuple[SyntheticTaskEvaluationResult, ...]
    efficiency: RunEfficiencySummary | None = None

    @property
    def total_tasks(self) -> int:
        return self.total_instances

    @property
    def resolved_tasks(self) -> int:
        return self.resolved_instances

    @property
    def unresolved_tasks(self) -> int:
        return self.unresolved_instances

    @property
    def patch_apply_failures(self) -> int:
        return sum(
            1
            for instance in self.instances
            if instance.patch_exists and not instance.patch_successfully_applied
        )

    @property
    def error_tasks(self) -> int:
        return self.error_instances


def validate_prepared_synthetic_workspace(
    workspace: PreparedSyntheticWorkspace,
) -> tuple[SyntheticValidationResult, ...]:
    results: list[SyntheticValidationResult] = []
    for prepared in workspace.tasks:
        task = prepared.task
        with tempfile.TemporaryDirectory(
            prefix=f"validate-{task.task_id}-",
            dir=str(workspace.workspace_dir),
        ) as temp_dir:
            validation_root = Path(temp_dir)
            repo_a_path, repo_b_path = copy_prepared_task_repositories(
                prepared_task=prepared,
                repo_b_path=workspace.repo_b_path,
                destination_root=validation_root,
            )

            buggy_run = _run_pytest(
                repo_a_path=repo_a_path,
                repo_b_path=repo_b_path,
                pytest_targets=task.pytest_targets,
            )
            gold_patch_applied, patch_error = _apply_patch_text(
                repo_a_path=repo_a_path,
                patch_text=task.gold_patch_path.read_text(encoding="utf-8"),
                patch_name=f"{task.task_id}-gold.patch",
            )
            repaired_run = _run_pytest(
                repo_a_path=repo_a_path,
                repo_b_path=repo_b_path,
                pytest_targets=task.pytest_targets,
            )

            if patch_error is not None:
                raise RuntimeError(
                    f"Gold patch failed to apply for {task.task_id}: {patch_error}"
                )
            if buggy_run.return_code == 0:
                raise RuntimeError(
                    f"Synthetic task {task.task_id} is invalid because the buggy state already passes."
                )
            if repaired_run.return_code != 0:
                raise RuntimeError(
                    f"Synthetic task {task.task_id} is invalid because the gold patch "
                    "does not make the declared tests pass."
                )

            results.append(
                SyntheticValidationResult(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    buggy_tests_failed=buggy_run.return_code != 0,
                    gold_patch_applied=gold_patch_applied,
                    repaired_tests_passed=repaired_run.return_code == 0,
                    failing_tests_before_patch=tuple(buggy_run.failing_tests),
                    failing_tests_after_patch=tuple(repaired_run.failing_tests),
                )
            )

    payload = {
        "family_name": workspace.family.config.family_name,
        "family_version": workspace.family.config.family_version,
        "seed": workspace.seed,
        "task_count": len(results),
        "results": [asdict(result) for result in results],
    }
    write_validation_report(workspace.validation_report_path, payload)
    return tuple(results)


def evaluate_synthetic_predictions(
    *,
    workspace: PreparedSyntheticWorkspace,
    predictions_path: Path,
    run_id: str,
    runs_root: Path = DEFAULT_SYNTHETIC_RUNS_ROOT,
    overwrite: bool = False,
    experiment: SyntheticExperimentMetadata | None = None,
) -> SyntheticRunSummary:
    if not run_id.strip():
        raise ValueError("run_id must not be empty.")

    predictions = load_synthetic_predictions(predictions_path)
    run_dir = runs_root.resolve() / run_id
    if run_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing synthetic run: {run_dir}")
        shutil.rmtree(run_dir)
    (run_dir / "tasks").mkdir(parents=True, exist_ok=True)

    results: list[SyntheticTaskEvaluationResult] = []
    generation_calls: list[GenerationCallMetrics] = []
    for prepared in workspace.tasks:
        task = prepared.task
        task_run_dir = run_dir / "tasks" / task.task_id
        task_run_dir.mkdir(parents=True, exist_ok=True)
        repo_a_path, repo_b_path = copy_prepared_task_repositories(
            prepared_task=prepared,
            repo_b_path=workspace.repo_b_path,
            destination_root=task_run_dir,
        )

        prediction = predictions.get(task.task_id)
        patch_apply_error: str | None = None
        patch_applied = False
        prediction_present = prediction is not None
        patch_exists = False
        if prediction is None:
            patch_apply_error = f"Missing prediction for synthetic task {task.task_id}"
            prediction = SyntheticPredictionRecord(
                task_id=task.task_id,
                task_type=task.task_type,
                model_name_or_path="",
                context_source="missing",
                model_patch="",
                full_output="",
            )
        else:
            patch_exists = bool(prediction.model_patch.strip())
            if (
                prediction.generation_input_tokens is not None
                and prediction.generation_output_tokens is not None
                and prediction.generation_total_tokens is not None
                and prediction.generation_latency_ms is not None
            ):
                generation_calls.append(
                    GenerationCallMetrics(
                        input_tokens=prediction.generation_input_tokens,
                        output_tokens=prediction.generation_output_tokens,
                        total_tokens=prediction.generation_total_tokens,
                        latency_ms=prediction.generation_latency_ms,
                    )
                )
        if patch_exists:
            patch_applied, patch_apply_error = _apply_patch_text(
                repo_a_path=repo_a_path,
                patch_text=prediction.model_patch,
                patch_name=f"{task.task_id}-model.patch",
            )

        pytest_run = _run_pytest(
            repo_a_path=repo_a_path,
            repo_b_path=repo_b_path,
            pytest_targets=task.pytest_targets,
        )
        resolved = patch_applied and pytest_run.return_code == 0
        result = SyntheticTaskEvaluationResult(
            task_id=task.task_id,
            task_type=task.task_type,
            model_name_or_path=prediction.model_name_or_path,
            context_source=prediction.context_source,
            prediction_present=prediction_present,
            patch_exists=patch_exists,
            patch_applied=patch_applied,
            tests_passed=pytest_run.return_code == 0,
            resolved=resolved,
            failing_tests=tuple(pytest_run.failing_tests),
            pytest_targets=task.pytest_targets,
            return_code=pytest_run.return_code,
            patch_apply_error=patch_apply_error,
            stdout=pytest_run.stdout,
            stderr=pytest_run.stderr,
            repo_a_path=repo_a_path,
            repo_b_path=repo_b_path,
        )
        _write_result_json(task_run_dir / "result.json", result)
        results.append(result)

    summary = _build_summary(
        family_name=workspace.family.config.family_name,
        family_version=workspace.family.config.family_version,
        run_id=run_id,
        run_dir=run_dir,
        predictions_path=predictions_path.resolve(),
        experiment=experiment or empty_synthetic_experiment_metadata(),
        results=tuple(results),
        generation_calls=tuple(generation_calls),
    )
    _write_summary_json(run_dir / "summary.json", summary)
    return summary


def summarize_synthetic_run(
    *,
    run_id: str,
    runs_root: Path = DEFAULT_SYNTHETIC_RUNS_ROOT,
) -> SyntheticRunSummary:
    run_dir = runs_root.resolve() / run_id
    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
        return _summary_from_json(raw)

    results: list[SyntheticTaskEvaluationResult] = []
    for result_path in sorted((run_dir / "tasks").glob("*/result.json")):
        raw = json.loads(result_path.read_text(encoding="utf-8"))
        results.append(_result_from_json(raw))

    if not results:
        raise FileNotFoundError(f"Synthetic run summary not found: {summary_path}")

    return _build_summary(
        family_name="synthetic",
        family_version="unknown",
        run_id=run_id,
        run_dir=run_dir,
        predictions_path=run_dir / "unknown_predictions.jsonl",
        experiment=empty_synthetic_experiment_metadata(),
        results=tuple(results),
    )


def list_synthetic_run_ids(
    *,
    runs_root: Path = DEFAULT_SYNTHETIC_RUNS_ROOT,
) -> tuple[str, ...]:
    root = runs_root.resolve()
    if not root.is_dir():
        return ()

    run_ids: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "summary.json").is_file() or (child / "tasks").is_dir():
            run_ids.append(child.name)
    return tuple(run_ids)


@dataclass(frozen=True)
class _PytestRun:
    return_code: int
    stdout: str
    stderr: str
    failing_tests: tuple[str, ...]


def _run_pytest(
    *,
    repo_a_path: Path,
    repo_b_path: Path | None,
    pytest_targets: tuple[str, ...],
) -> _PytestRun:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    extra_paths = [str(repo_a_path.resolve())]
    if repo_b_path is not None:
        extra_paths.append(str(repo_b_path.resolve()))
    env["PYTHONPATH"] = (
        ":".join(extra_paths) + (":" + existing_pythonpath if existing_pythonpath else "")
    )

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *pytest_targets],
        cwd=repo_a_path,
        text=True,
        capture_output=True,
        env=env,
    )
    combined_output = "\n".join(
        part for part in [completed.stdout.strip(), completed.stderr.strip()] if part
    )
    failing_tests = _extract_failing_tests(combined_output, pytest_targets, completed.returncode)
    return _PytestRun(
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        failing_tests=failing_tests,
    )


def _apply_patch_text(
    *,
    repo_a_path: Path,
    patch_text: str,
    patch_name: str,
) -> tuple[bool, str | None]:
    normalized_patch = _normalize_patch_text(patch_text).strip()
    if not normalized_patch:
        return False, "Empty patch"
    if not normalized_patch.endswith("\n"):
        normalized_patch += "\n"

    patch_path = repo_a_path / patch_name
    patch_path.write_text(normalized_patch, encoding="utf-8")
    try:
        completed = subprocess.run(
            ["git", "apply", str(patch_path)],
            cwd=repo_a_path,
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        stdout = exc.stdout.strip()
        return False, stderr or stdout or str(exc)
    else:
        _ = completed
        return True, None
    finally:
        patch_path.unlink(missing_ok=True)


def _normalize_patch_text(patch_text: str) -> str:
    normalized_lines: list[str] = []
    for line in patch_text.splitlines():
        normalized_line = line
        for prefix in ("diff --git a/synthetic/", "--- a/synthetic/", "+++ b/synthetic/"):
            if normalized_line.startswith(prefix):
                marker, remainder = normalized_line.split("synthetic/", 1)
                if "/" in remainder:
                    normalized_line = marker + remainder.split("/", 1)[1]
                break
        normalized_lines.append(normalized_line)
    return "\n".join(normalized_lines)


def _extract_failing_tests(
    output: str,
    pytest_targets: tuple[str, ...],
    return_code: int,
) -> tuple[str, ...]:
    failures: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(_FAILED_TEST_PREFIXES):
            test_name = stripped.split(" - ", 1)[0]
            for prefix in _FAILED_TEST_PREFIXES:
                if test_name.startswith(prefix):
                    test_name = test_name.removeprefix(prefix).strip()
                    break
            if test_name and test_name not in failures:
                failures.append(test_name)
    if not failures and return_code != 0:
        return pytest_targets
    return tuple(failures)


def _build_summary(
    *,
    family_name: str,
    family_version: str,
    run_id: str,
    run_dir: Path,
    predictions_path: Path,
    experiment: SyntheticExperimentMetadata,
    results: tuple[SyntheticTaskEvaluationResult, ...],
    generation_calls: tuple[GenerationCallMetrics, ...] = (),
) -> SyntheticRunSummary:
    instances = tuple(_instance_summary_from_result(result) for result in results)
    total_instances = len(results)
    submitted_ids = tuple(result.task_id for result in results if result.prediction_present)
    completed_ids = submitted_ids
    resolved_ids = tuple(instance.task_id for instance in instances if instance.resolved)
    unresolved_ids = tuple(instance.task_id for instance in instances if not instance.resolved)
    empty_patch_ids = tuple(
        instance.task_id
        for instance in instances
        if instance.prediction_present and not instance.patch_exists
    )
    error_ids = tuple(
        result.task_id
        for result in results
        if not result.prediction_present or (result.patch_exists and not result.patch_applied)
    )
    generation = aggregate_generation_metrics(
        calls=generation_calls,
        model_name=experiment.generation_model_name_or_path,
        region_name=experiment.generation_region_name,
    )
    efficiency = RunEfficiencySummary(
        generation=generation,
        indexing_duration_seconds=0.0,
        wiki_duration_seconds=0.0,
        retrieval_duration_seconds=0.0,
        generation_duration_seconds=0.0,
        total_duration_seconds=0.0,
        retrieval_request_count=0,
        retrieval_query_tokens_estimate=None,
        retrieval_query_cost_estimate_usd=None,
    )
    return SyntheticRunSummary(
        family_name=family_name,
        family_version=family_version,
        run_id=run_id,
        run_dir=run_dir,
        predictions_path=predictions_path,
        experiment=experiment,
        total_instances=total_instances,
        submitted_instances=len(submitted_ids),
        completed_instances=len(completed_ids),
        resolved_instances=len(resolved_ids),
        unresolved_instances=len(unresolved_ids),
        empty_patch_instances=len(empty_patch_ids),
        error_instances=len(error_ids),
        submitted_ids=submitted_ids,
        completed_ids=completed_ids,
        resolved_ids=resolved_ids,
        unresolved_ids=unresolved_ids,
        empty_patch_ids=empty_patch_ids,
        error_ids=error_ids,
        instances=instances,
        results=results,
        efficiency=efficiency,
    )


def _instance_summary_from_result(result: SyntheticTaskEvaluationResult) -> SyntheticInstanceSummary:
    failing_tests = set(result.failing_tests)
    fail_to_pass_successes = tuple(
        test_name for test_name in result.pytest_targets if test_name not in failing_tests
    )
    fail_to_pass_failures = tuple(
        test_name for test_name in result.pytest_targets if test_name in failing_tests
    )
    return SyntheticInstanceSummary(
        task_id=result.task_id,
        task_type=result.task_type,
        model_name_or_path=result.model_name_or_path,
        context_source=result.context_source,
        prediction_present=result.prediction_present,
        resolved=result.resolved,
        patch_exists=result.patch_exists,
        patch_successfully_applied=result.patch_applied,
        fail_to_pass_successes=fail_to_pass_successes,
        fail_to_pass_failures=fail_to_pass_failures,
        pass_to_pass_failures=(),
        patch_apply_error=result.patch_apply_error,
    )


def _write_result_json(path: Path, result: SyntheticTaskEvaluationResult) -> None:
    payload = {
        **asdict(result),
        "repo_a_path": str(result.repo_a_path.resolve()),
        "repo_b_path": str(result.repo_b_path.resolve()) if result.repo_b_path is not None else "",
        "failing_tests": list(result.failing_tests),
        "pytest_targets": list(result.pytest_targets),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_summary_json(path: Path, summary: SyntheticRunSummary) -> None:
    payload = {
        "schema_version": 2,
        "family_name": summary.family_name,
        "family_version": summary.family_version,
        "run_id": summary.run_id,
        "run_dir": str(summary.run_dir.resolve()),
        "predictions_path": str(summary.predictions_path.resolve())
        if str(summary.predictions_path)
        else "",
        "experiment": summary.experiment.to_json(),
        "total_instances": summary.total_instances,
        "submitted_instances": summary.submitted_instances,
        "completed_instances": summary.completed_instances,
        "resolved_instances": summary.resolved_instances,
        "unresolved_instances": summary.unresolved_instances,
        "empty_patch_instances": summary.empty_patch_instances,
        "error_instances": summary.error_instances,
        "submitted_ids": list(summary.submitted_ids),
        "completed_ids": list(summary.completed_ids),
        "resolved_ids": list(summary.resolved_ids),
        "unresolved_ids": list(summary.unresolved_ids),
        "empty_patch_ids": list(summary.empty_patch_ids),
        "error_ids": list(summary.error_ids),
        "total_tasks": summary.total_tasks,
        "resolved_tasks": summary.resolved_tasks,
        "unresolved_tasks": summary.unresolved_tasks,
        "patch_apply_failures": summary.patch_apply_failures,
        "error_tasks": summary.error_tasks,
        "instances": [
            {
                "task_id": instance.task_id,
                "task_type": instance.task_type,
                "model_name_or_path": instance.model_name_or_path,
                "context_source": instance.context_source,
                "prediction_present": instance.prediction_present,
                "resolved": instance.resolved,
                "patch_exists": instance.patch_exists,
                "patch_successfully_applied": instance.patch_successfully_applied,
                "fail_to_pass_successes": list(instance.fail_to_pass_successes),
                "fail_to_pass_failures": list(instance.fail_to_pass_failures),
                "pass_to_pass_failures": list(instance.pass_to_pass_failures),
                "patch_apply_error": instance.patch_apply_error,
            }
            for instance in summary.instances
        ],
        "results": [
            {
                "task_id": result.task_id,
                "task_type": result.task_type,
                "model_name_or_path": result.model_name_or_path,
                "context_source": result.context_source,
                "prediction_present": result.prediction_present,
                "patch_exists": result.patch_exists,
                "patch_applied": result.patch_applied,
                "tests_passed": result.tests_passed,
                "resolved": result.resolved,
                "failing_tests": list(result.failing_tests),
                "pytest_targets": list(result.pytest_targets),
                "return_code": result.return_code,
                "patch_apply_error": result.patch_apply_error,
                "repo_a_path": str(result.repo_a_path.resolve()),
                "repo_b_path": str(result.repo_b_path.resolve()) if result.repo_b_path is not None else "",
            }
            for result in summary.results
        ],
        "efficiency": summary.efficiency.to_json() if summary.efficiency is not None else None,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _summary_from_json(raw: dict[str, object]) -> SyntheticRunSummary:
    raw_results = raw.get("results", [])
    results = (
        tuple(_result_from_json(_as_mapping(item)) for item in raw_results if isinstance(item, Mapping))
        if isinstance(raw_results, list)
        else ()
    )
    experiment = synthetic_experiment_metadata_from_json(raw)
    computed = _build_summary(
        family_name=_string_value(raw, "family_name"),
        family_version=_string_value(raw, "family_version"),
        run_id=_string_value(raw, "run_id"),
        run_dir=Path(_string_value(raw, "run_dir")),
        predictions_path=Path(_string_value(raw, "predictions_path")),
        experiment=experiment,
        results=results,
    )
    efficiency = _efficiency_from_json(raw.get("efficiency"))
    raw_instances = raw.get("instances", [])
    if isinstance(raw_instances, list) and raw_instances:
        instances = tuple(
            _instance_from_json(_as_mapping(item))
            for item in raw_instances
            if isinstance(item, Mapping)
        )
    else:
        instances = computed.instances
    return SyntheticRunSummary(
        family_name=computed.family_name,
        family_version=computed.family_version,
        run_id=computed.run_id,
        run_dir=computed.run_dir,
        predictions_path=computed.predictions_path,
        experiment=experiment,
        total_instances=_int_value(
            raw,
            "total_instances",
            _int_value(raw, "total_tasks", computed.total_instances),
        ),
        submitted_instances=_int_value(raw, "submitted_instances", computed.submitted_instances),
        completed_instances=_int_value(raw, "completed_instances", computed.completed_instances),
        resolved_instances=_int_value(
            raw,
            "resolved_instances",
            _int_value(raw, "resolved_tasks", computed.resolved_instances),
        ),
        unresolved_instances=_int_value(
            raw,
            "unresolved_instances",
            _int_value(raw, "unresolved_tasks", computed.unresolved_instances),
        ),
        empty_patch_instances=_int_value(raw, "empty_patch_instances", computed.empty_patch_instances),
        error_instances=_int_value(
            raw,
            "error_instances",
            _int_value(raw, "error_tasks", computed.error_instances),
        ),
        submitted_ids=_string_tuple_value(raw, "submitted_ids") or computed.submitted_ids,
        completed_ids=_string_tuple_value(raw, "completed_ids") or computed.completed_ids,
        resolved_ids=_string_tuple_value(raw, "resolved_ids") or computed.resolved_ids,
        unresolved_ids=_string_tuple_value(raw, "unresolved_ids") or computed.unresolved_ids,
        empty_patch_ids=_string_tuple_value(raw, "empty_patch_ids") or computed.empty_patch_ids,
        error_ids=_string_tuple_value(raw, "error_ids") or computed.error_ids,
        instances=instances,
        results=results,
        efficiency=efficiency or computed.efficiency,
    )


def _result_from_json(raw: Mapping[str, object]) -> SyntheticTaskEvaluationResult:
    failing_tests = _string_tuple_value(raw, "failing_tests")
    pytest_targets = _string_tuple_value(raw, "pytest_targets")
    return SyntheticTaskEvaluationResult(
        task_id=_string_value(raw, "task_id"),
        task_type=_string_value(raw, "task_type"),
        model_name_or_path=_string_value(raw, "model_name_or_path"),
        context_source=_string_value(raw, "context_source"),
        prediction_present=_bool_value(raw, "prediction_present", _infer_prediction_present(raw)),
        patch_exists=_bool_value(raw, "patch_exists", _infer_patch_exists(raw)),
        patch_applied=bool(raw.get("patch_applied", False)),
        tests_passed=bool(raw.get("tests_passed", False)),
        resolved=bool(raw.get("resolved", False)),
        failing_tests=failing_tests,
        pytest_targets=pytest_targets,
        return_code=_int_value(raw, "return_code", 1),
        patch_apply_error=(
            _string_value(raw, "patch_apply_error")
            if raw.get("patch_apply_error") is not None
            else None
        ),
        stdout=_string_value(raw, "stdout"),
        stderr=_string_value(raw, "stderr"),
        repo_a_path=Path(_string_value(raw, "repo_a_path")),
        repo_b_path=Path(_string_value(raw, "repo_b_path")) if _string_value(raw, "repo_b_path") else None,
    )


def _instance_from_json(raw: Mapping[str, object]) -> SyntheticInstanceSummary:
    return SyntheticInstanceSummary(
        task_id=_string_value(raw, "task_id"),
        task_type=_string_value(raw, "task_type"),
        model_name_or_path=_string_value(raw, "model_name_or_path"),
        context_source=_string_value(raw, "context_source"),
        prediction_present=_bool_value(raw, "prediction_present", True),
        resolved=bool(raw.get("resolved", False)),
        patch_exists=_bool_value(raw, "patch_exists", False),
        patch_successfully_applied=_bool_value(raw, "patch_successfully_applied", False),
        fail_to_pass_successes=_string_tuple_value(raw, "fail_to_pass_successes"),
        fail_to_pass_failures=_string_tuple_value(raw, "fail_to_pass_failures"),
        pass_to_pass_failures=_string_tuple_value(raw, "pass_to_pass_failures"),
        patch_apply_error=(
            _string_value(raw, "patch_apply_error")
            if raw.get("patch_apply_error") is not None
            else None
        ),
    )


def _string_value(data: Mapping[str, object], key: str, default: str = "") -> str:
    return str(data.get(key, default)).strip()


def _int_value(data: Mapping[str, object], key: str, default: int = 0) -> int:
    value = data.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value)
    return default


def _bool_value(data: Mapping[str, object], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def _string_tuple_value(data: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _infer_prediction_present(raw: Mapping[str, object]) -> bool:
    return _string_value(raw, "context_source") != "missing"


def _infer_patch_exists(raw: Mapping[str, object]) -> bool:
    if bool(raw.get("patch_applied", False)):
        return True
    patch_apply_error = _string_value(raw, "patch_apply_error")
    if not patch_apply_error:
        return False
    if patch_apply_error == "Empty patch":
        return False
    if patch_apply_error.startswith("Missing prediction for synthetic task "):
        return False
    return True


def _as_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("Expected a mapping value.")
    return cast(Mapping[str, object], value)


def _efficiency_from_json(value: object) -> RunEfficiencySummary | None:
    if not isinstance(value, Mapping):
        return None
    generation_raw = value.get("generation")
    if not isinstance(generation_raw, Mapping):
        return None
    generation = GenerationAggregateMetrics(
        request_count=_int_value(generation_raw, "request_count", 0),
        input_tokens=_int_value(generation_raw, "input_tokens", 0),
        output_tokens=_int_value(generation_raw, "output_tokens", 0),
        total_tokens=_int_value(generation_raw, "total_tokens", 0),
        latency_ms_total=float(generation_raw.get("latency_ms_total", 0.0) or 0.0),
        latency_ms_avg=float(generation_raw.get("latency_ms_avg", 0.0) or 0.0),
        estimated_cost_usd=(
            float(generation_raw.get("estimated_cost_usd"))
            if generation_raw.get("estimated_cost_usd") is not None
            else None
        ),
    )
    return RunEfficiencySummary(
        generation=generation,
        indexing_duration_seconds=float(value.get("indexing_duration_seconds", 0.0) or 0.0),
        wiki_duration_seconds=float(value.get("wiki_duration_seconds", 0.0) or 0.0),
        retrieval_duration_seconds=float(value.get("retrieval_duration_seconds", 0.0) or 0.0),
        generation_duration_seconds=float(value.get("generation_duration_seconds", 0.0) or 0.0),
        total_duration_seconds=float(value.get("total_duration_seconds", 0.0) or 0.0),
        retrieval_request_count=_int_value(value, "retrieval_request_count", 0),
        retrieval_query_tokens_estimate=(
            _int_value(value, "retrieval_query_tokens_estimate")
            if value.get("retrieval_query_tokens_estimate") is not None
            else None
        ),
        retrieval_query_cost_estimate_usd=(
            float(value.get("retrieval_query_cost_estimate_usd"))
            if value.get("retrieval_query_cost_estimate_usd") is not None
            else None
        ),
    )
