from __future__ import annotations

from collections.abc import Sequence
import math
from dataclasses import dataclass
from pathlib import Path

from .eval import (
    SyntheticInstanceSummary,
    SyntheticRunSummary,
    SyntheticTaskEvaluationResult,
    summarize_synthetic_run,
)
from .workspace import DEFAULT_SYNTHETIC_RUNS_ROOT


@dataclass(frozen=True)
class SyntheticTaskComparison:
    task_id: str
    task_type: str
    baseline_status: str
    lighthouse_status: str
    baseline_context_source: str
    lighthouse_context_source: str
    baseline_resolved: bool
    lighthouse_resolved: bool
    baseline_patch_exists: bool
    lighthouse_patch_exists: bool
    baseline_patch_successfully_applied: bool
    lighthouse_patch_successfully_applied: bool
    baseline_failing_tests: int
    lighthouse_failing_tests: int
    baseline_pass_to_pass_failures: int
    lighthouse_pass_to_pass_failures: int
    delta: str


@dataclass(frozen=True)
class SyntheticRunComparison:
    baseline_label: str
    lighthouse_label: str
    baseline: SyntheticRunSummary
    lighthouse: SyntheticRunSummary
    improved_tasks: int
    regressed_tasks: int
    unchanged_tasks: int
    task_comparisons: tuple[SyntheticTaskComparison, ...]


@dataclass(frozen=True)
class SyntheticScoreRow:
    label: str
    run_id: str
    total_instances: int
    resolved_instances: int
    unresolved_instances: int
    score_pct: float


@dataclass(frozen=True)
class SyntheticPassAtKTaskRow:
    task_id: str
    task_type: str
    samples: int
    successes: int
    pass_at_k: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class SyntheticPassAtKSummary:
    family_name: str
    family_version: str
    run_ids: tuple[str, ...]
    k_values: tuple[int, ...]
    task_rows: tuple[SyntheticPassAtKTaskRow, ...]
    macro_pass_at_k: tuple[tuple[int, float], ...]


def compare_synthetic_runs(
    *,
    baseline_run_id: str,
    lighthouse_run_id: str,
    runs_root: Path = DEFAULT_SYNTHETIC_RUNS_ROOT,
    baseline_label: str = "baseline",
    lighthouse_label: str = "lighthouse",
) -> SyntheticRunComparison:
    baseline = summarize_synthetic_run(run_id=baseline_run_id, runs_root=runs_root)
    lighthouse = summarize_synthetic_run(run_id=lighthouse_run_id, runs_root=runs_root)

    if baseline.family_name != lighthouse.family_name:
        raise ValueError(
            "Synthetic run families do not match: "
            f"{baseline.family_name!r} != {lighthouse.family_name!r}"
        )
    if baseline.family_version != lighthouse.family_version:
        raise ValueError(
            "Synthetic run family versions do not match: "
            f"{baseline.family_version!r} != {lighthouse.family_version!r}"
        )

    baseline_by_task = {result.task_id: result for result in baseline.results}
    lighthouse_by_task = {result.task_id: result for result in lighthouse.results}
    baseline_instances = {instance.task_id: instance for instance in baseline.instances}
    lighthouse_instances = {
        instance.task_id: instance for instance in lighthouse.instances
    }
    baseline_ids = set(baseline_by_task)
    lighthouse_ids = set(lighthouse_by_task)
    if baseline_ids != lighthouse_ids:
        missing_from_lighthouse = sorted(baseline_ids - lighthouse_ids)
        missing_from_baseline = sorted(lighthouse_ids - baseline_ids)
        raise ValueError(
            "Synthetic runs do not cover the same task ids. "
            f"Missing from {lighthouse_label}: {missing_from_lighthouse or 'none'}. "
            f"Missing from {baseline_label}: {missing_from_baseline or 'none'}."
        )

    comparisons: list[SyntheticTaskComparison] = []
    improved_tasks = 0
    regressed_tasks = 0
    unchanged_tasks = 0

    for task_id in sorted(baseline_ids):
        baseline_result = baseline_by_task[task_id]
        lighthouse_result = lighthouse_by_task[task_id]
        delta = _classify_delta(baseline_result, lighthouse_result)
        baseline_instance = _instance_summary_for(task_id, baseline_instances)
        lighthouse_instance = _instance_summary_for(task_id, lighthouse_instances)
        if delta == "improved":
            improved_tasks += 1
        elif delta == "regressed":
            regressed_tasks += 1
        else:
            unchanged_tasks += 1

        comparisons.append(
            SyntheticTaskComparison(
                task_id=task_id,
                task_type=baseline_result.task_type,
                baseline_status=_task_status(baseline_result),
                lighthouse_status=_task_status(lighthouse_result),
                baseline_context_source=baseline_result.context_source,
                lighthouse_context_source=lighthouse_result.context_source,
                baseline_resolved=baseline_instance.resolved,
                lighthouse_resolved=lighthouse_instance.resolved,
                baseline_patch_exists=baseline_instance.patch_exists,
                lighthouse_patch_exists=lighthouse_instance.patch_exists,
                baseline_patch_successfully_applied=baseline_instance.patch_successfully_applied,
                lighthouse_patch_successfully_applied=lighthouse_instance.patch_successfully_applied,
                baseline_failing_tests=len(baseline_instance.fail_to_pass_failures),
                lighthouse_failing_tests=len(lighthouse_instance.fail_to_pass_failures),
                baseline_pass_to_pass_failures=len(
                    baseline_instance.pass_to_pass_failures
                ),
                lighthouse_pass_to_pass_failures=len(
                    lighthouse_instance.pass_to_pass_failures
                ),
                delta=delta,
            )
        )

    return SyntheticRunComparison(
        baseline_label=baseline_label,
        lighthouse_label=lighthouse_label,
        baseline=baseline,
        lighthouse=lighthouse,
        improved_tasks=improved_tasks,
        regressed_tasks=regressed_tasks,
        unchanged_tasks=unchanged_tasks,
        task_comparisons=tuple(comparisons),
    )


def render_synthetic_comparison_tables(comparison: SyntheticRunComparison) -> str:
    overall_headers = (
        "run",
        "total_instances",
        "submitted_instances",
        "completed_instances",
        "resolved_instances",
        "unresolved_instances",
        "empty_patch_instances",
        "error_instances",
    )
    overall_rows = [
        (
            comparison.baseline_label,
            str(comparison.baseline.total_instances),
            str(comparison.baseline.submitted_instances),
            str(comparison.baseline.completed_instances),
            str(comparison.baseline.resolved_instances),
            str(comparison.baseline.unresolved_instances),
            str(comparison.baseline.empty_patch_instances),
            str(comparison.baseline.error_instances),
        ),
        (
            comparison.lighthouse_label,
            str(comparison.lighthouse.total_instances),
            str(comparison.lighthouse.submitted_instances),
            str(comparison.lighthouse.completed_instances),
            str(comparison.lighthouse.resolved_instances),
            str(comparison.lighthouse.unresolved_instances),
            str(comparison.lighthouse.empty_patch_instances),
            str(comparison.lighthouse.error_instances),
        ),
        (
            "delta",
            _signed_delta(
                comparison.lighthouse.total_instances
                - comparison.baseline.total_instances
            ),
            _signed_delta(
                comparison.lighthouse.submitted_instances
                - comparison.baseline.submitted_instances
            ),
            _signed_delta(
                comparison.lighthouse.completed_instances
                - comparison.baseline.completed_instances
            ),
            _signed_delta(
                comparison.lighthouse.resolved_instances
                - comparison.baseline.resolved_instances
            ),
            _signed_delta(
                comparison.lighthouse.unresolved_instances
                - comparison.baseline.unresolved_instances
            ),
            _signed_delta(
                comparison.lighthouse.empty_patch_instances
                - comparison.baseline.empty_patch_instances
            ),
            _signed_delta(
                comparison.lighthouse.error_instances
                - comparison.baseline.error_instances
            ),
        ),
    ]

    task_headers = (
        "instance_id",
        "task_type",
        f"{comparison.baseline_label}.status",
        f"{comparison.lighthouse_label}.status",
        f"{comparison.baseline_label}.resolved",
        f"{comparison.lighthouse_label}.resolved",
        f"{comparison.baseline_label}.patch_exists",
        f"{comparison.lighthouse_label}.patch_exists",
        f"{comparison.baseline_label}.patch_successfully_applied",
        f"{comparison.lighthouse_label}.patch_successfully_applied",
        f"{comparison.baseline_label}.FAIL_TO_PASS.failure",
        f"{comparison.lighthouse_label}.FAIL_TO_PASS.failure",
        f"{comparison.baseline_label}.PASS_TO_PASS.failure",
        f"{comparison.lighthouse_label}.PASS_TO_PASS.failure",
        "delta",
    )
    task_rows = [
        (
            task.task_id,
            task.task_type,
            task.baseline_status,
            task.lighthouse_status,
            _bool_cell(task.baseline_resolved),
            _bool_cell(task.lighthouse_resolved),
            _bool_cell(task.baseline_patch_exists),
            _bool_cell(task.lighthouse_patch_exists),
            _bool_cell(task.baseline_patch_successfully_applied),
            _bool_cell(task.lighthouse_patch_successfully_applied),
            str(task.baseline_failing_tests),
            str(task.lighthouse_failing_tests),
            str(task.baseline_pass_to_pass_failures),
            str(task.lighthouse_pass_to_pass_failures),
            task.delta,
        )
        for task in comparison.task_comparisons
    ]

    summary_lines = [
        f"Family: {comparison.baseline.family_name} [v{comparison.baseline.family_version}]",
        f"Baseline run: {comparison.baseline.run_id}",
        _format_experiment_line(comparison.baseline_label, comparison.baseline),
        f"Lighthouse run: {comparison.lighthouse.run_id}",
        _format_experiment_line(comparison.lighthouse_label, comparison.lighthouse),
        (
            "Outcome counts: "
            f"improved={comparison.improved_tasks}, "
            f"regressed={comparison.regressed_tasks}, "
            f"unchanged={comparison.unchanged_tasks}"
        ),
        "",
        "Overall",
        _render_table(overall_headers, overall_rows),
        "",
        "Per-task",
        _render_table(task_headers, task_rows),
    ]
    return "\n".join(summary_lines)


def build_synthetic_score_rows(
    *,
    baseline: SyntheticRunSummary,
    retrieval_runs: dict[str, SyntheticRunSummary],
) -> tuple[SyntheticScoreRow, ...]:
    rows = [_score_row("baseline", baseline)]
    for label in ("code", "wiki", "ast", "combined", "grep"):
        summary = retrieval_runs.get(label)
        if summary is None:
            continue
        rows.append(_score_row(label, summary))
    for label, summary in sorted(retrieval_runs.items()):
        if label in {"code", "wiki", "ast", "combined", "grep"}:
            continue
        rows.append(_score_row(label, summary))
    return tuple(rows)


def render_synthetic_score_table(rows: Sequence[SyntheticScoreRow]) -> str:
    headers = (
        "run",
        "run_id",
        "resolved_instances",
        "total_instances",
        "unresolved_instances",
        "score_pct",
    )
    table_rows = [
        (
            row.label,
            row.run_id,
            str(row.resolved_instances),
            str(row.total_instances),
            str(row.unresolved_instances),
            f"{row.score_pct:.1f}%",
        )
        for row in rows
    ]
    return _render_table(headers, table_rows)


def compute_synthetic_pass_at_k(
    *,
    run_ids: Sequence[str],
    k_values: Sequence[int],
    runs_root: Path = DEFAULT_SYNTHETIC_RUNS_ROOT,
) -> SyntheticPassAtKSummary:
    normalized_run_ids = tuple(run_id.strip() for run_id in run_ids if run_id.strip())
    if not normalized_run_ids:
        raise ValueError("Provide at least one run id.")

    normalized_k_values = tuple(sorted({k for k in k_values if k > 0}))
    if not normalized_k_values:
        raise ValueError("Provide at least one positive k value.")

    summaries = [
        summarize_synthetic_run(run_id=run_id, runs_root=runs_root)
        for run_id in normalized_run_ids
    ]
    first = summaries[0]
    for summary in summaries[1:]:
        if summary.family_name != first.family_name:
            raise ValueError(
                "All runs must share the same synthetic family_name; got "
                f"{first.family_name!r} and {summary.family_name!r}."
            )
        if summary.family_version != first.family_version:
            raise ValueError(
                "All runs must share the same synthetic family_version; got "
                f"{first.family_version!r} and {summary.family_version!r}."
            )

    task_ids = {instance.task_id for instance in first.instances}
    for summary in summaries[1:]:
        other_ids = {instance.task_id for instance in summary.instances}
        if other_ids != task_ids:
            missing = sorted(task_ids - other_ids)
            extra = sorted(other_ids - task_ids)
            raise ValueError(
                "All runs must cover the same task ids for pass@k aggregation. "
                f"Missing: {missing or 'none'}. Extra: {extra or 'none'}."
            )

    instances_by_run = [
        {instance.task_id: instance for instance in summary.instances}
        for summary in summaries
    ]

    task_rows: list[SyntheticPassAtKTaskRow] = []
    for task_id in sorted(task_ids):
        resolved_flags = [instances[task_id].resolved for instances in instances_by_run]
        samples = len(resolved_flags)
        successes = sum(1 for flag in resolved_flags if flag)
        task_type = instances_by_run[0][task_id].task_type
        task_rows.append(
            SyntheticPassAtKTaskRow(
                task_id=task_id,
                task_type=task_type,
                samples=samples,
                successes=successes,
                pass_at_k=tuple(
                    (k, _pass_at_k_from_counts(samples=samples, successes=successes, k=k))
                    for k in normalized_k_values
                ),
            )
        )

    macro: list[tuple[int, float]] = []
    for k in normalized_k_values:
        values = [dict(row.pass_at_k)[k] for row in task_rows]
        macro.append((k, (sum(values) / len(values)) if values else 0.0))

    return SyntheticPassAtKSummary(
        family_name=first.family_name,
        family_version=first.family_version,
        run_ids=normalized_run_ids,
        k_values=normalized_k_values,
        task_rows=tuple(task_rows),
        macro_pass_at_k=tuple(macro),
    )


def render_synthetic_pass_at_k_table(summary: SyntheticPassAtKSummary) -> str:
    macro_headers = ("k", "macro_pass@k")
    macro_rows = [(str(k), f"{value * 100:.1f}%") for k, value in summary.macro_pass_at_k]

    task_headers = (
        "task_id",
        "task_type",
        "samples",
        "successes",
        *(f"pass@{k}" for k in summary.k_values),
    )
    task_rows = [
        (
            row.task_id,
            row.task_type,
            str(row.samples),
            str(row.successes),
            *(f"{dict(row.pass_at_k)[k] * 100:.1f}%" for k in summary.k_values),
        )
        for row in summary.task_rows
    ]

    lines = [
        f"Family: {summary.family_name} [v{summary.family_version}]",
        f"Runs: {', '.join(summary.run_ids)}",
        "",
        "Macro pass@k",
        _render_table(macro_headers, macro_rows),
        "",
        "Per-task pass@k",
        _render_table(task_headers, task_rows),
    ]
    return "\n".join(lines)


def _classify_delta(
    baseline: SyntheticTaskEvaluationResult,
    lighthouse: SyntheticTaskEvaluationResult,
) -> str:
    if lighthouse.resolved and not baseline.resolved:
        return "improved"
    if baseline.resolved and not lighthouse.resolved:
        return "regressed"
    if len(lighthouse.failing_tests) < len(baseline.failing_tests):
        return "improved"
    if len(lighthouse.failing_tests) > len(baseline.failing_tests):
        return "regressed"
    if _task_status(lighthouse) != _task_status(baseline):
        if _status_rank(_task_status(lighthouse)) > _status_rank(
            _task_status(baseline)
        ):
            return "improved"
        if _status_rank(_task_status(lighthouse)) < _status_rank(
            _task_status(baseline)
        ):
            return "regressed"
    return "unchanged"


def _task_status(result: SyntheticTaskEvaluationResult) -> str:
    if result.resolved:
        return "resolved"
    if not result.prediction_present:
        return "error"
    if not result.patch_exists:
        return "missing_patch"
    if not result.patch_applied:
        return "patch_failed"
    return "unresolved"


def _status_rank(status: str) -> int:
    ranks = {
        "error": 0,
        "missing_patch": 1,
        "patch_failed": 2,
        "unresolved": 3,
        "resolved": 4,
    }
    return ranks.get(status, -1)


def _signed_delta(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def _bool_cell(value: bool) -> str:
    return "true" if value else "false"


def _score_row(label: str, summary: SyntheticRunSummary) -> SyntheticScoreRow:
    total = summary.total_instances
    score_pct = 0.0 if total == 0 else (summary.resolved_instances / total) * 100.0
    return SyntheticScoreRow(
        label=label,
        run_id=summary.run_id,
        total_instances=summary.total_instances,
        resolved_instances=summary.resolved_instances,
        unresolved_instances=summary.unresolved_instances,
        score_pct=score_pct,
    )


def _format_experiment_line(label: str, summary: SyntheticRunSummary) -> str:
    experiment = summary.experiment
    parts: list[str] = []
    if experiment.generation_model_name_or_path:
        parts.append(f"generation={experiment.generation_model_name_or_path}")
    if experiment.generation_region_name:
        parts.append(f"region={experiment.generation_region_name}")
    if experiment.indexing_embedding.strategy or experiment.indexing_embedding.model:
        parts.append(
            "index-embed="
            f"{experiment.indexing_embedding.strategy or 'unknown'}"
            f"/{experiment.indexing_embedding.model or 'unknown'}"
        )
    if experiment.query_embedding.strategy or experiment.query_embedding.model:
        parts.append(
            "query-embed="
            f"{experiment.query_embedding.strategy or 'unknown'}"
            f"/{experiment.query_embedding.model or 'unknown'}"
        )
    if experiment.context_source:
        parts.append(f"context={experiment.context_source}")
    if experiment.search_top_k is not None:
        parts.append(f"top_k={experiment.search_top_k}")
    details = ", ".join(parts) if parts else "no experiment metadata recorded"
    return f"{label.capitalize()} config: {details}"


def _pass_at_k_from_counts(*, samples: int, successes: int, k: int) -> float:
    if samples <= 0:
        return 0.0
    if successes <= 0:
        return 0.0
    if k >= samples:
        return 1.0
    if samples - successes < k:
        return 1.0
    numerator = math.comb(samples - successes, k)
    denominator = math.comb(samples, k)
    return 1.0 - (numerator / denominator)


def _render_table(headers: tuple[str, ...], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_row(row: Sequence[str]) -> str:
        return " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    lines = [format_row(headers), separator]
    lines.extend(format_row(row) for row in rows)
    return "\n".join(lines)


def _instance_summary_for(
    task_id: str,
    instances: dict[str, SyntheticInstanceSummary],
) -> SyntheticInstanceSummary:
    try:
        return instances[task_id]
    except KeyError as exc:
        raise ValueError(f"Missing synthetic instance summary for {task_id!r}") from exc
