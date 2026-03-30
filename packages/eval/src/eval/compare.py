from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from eval.summary import HarnessInstanceSummary, HarnessRunSummary


@dataclass(frozen=True)
class SWEBenchInstanceComparison:
    instance_id: str
    repo: str
    baseline_status: str
    lighthouse_status: str
    baseline_resolved: bool
    lighthouse_resolved: bool
    baseline_patch_exists: bool
    lighthouse_patch_exists: bool
    baseline_patch_successfully_applied: bool
    lighthouse_patch_successfully_applied: bool
    baseline_fail_to_pass_failures: int
    lighthouse_fail_to_pass_failures: int
    baseline_pass_to_pass_failures: int
    lighthouse_pass_to_pass_failures: int
    delta: str


@dataclass(frozen=True)
class SWEBenchRunComparison:
    baseline_label: str
    lighthouse_label: str
    baseline: HarnessRunSummary
    lighthouse: HarnessRunSummary
    improved_instances: int
    regressed_instances: int
    unchanged_instances: int
    instance_comparisons: tuple[SWEBenchInstanceComparison, ...]


@dataclass(frozen=True)
class SWEBenchScoreRow:
    label: str
    run_id: str
    total_instances: int
    resolved_instances: int
    unresolved_instances: int
    score_pct: float


def compare_swebench_runs(
    *,
    baseline: HarnessRunSummary,
    lighthouse: HarnessRunSummary,
    baseline_run_id: str,
    lighthouse_run_id: str,
    task_repo_map: Mapping[str, str] | None = None,
    baseline_label: str = "baseline",
    lighthouse_label: str = "lighthouse",
) -> SWEBenchRunComparison:
    baseline_by_id = {inst.instance_id: inst for inst in baseline.instances}
    lighthouse_by_id = {inst.instance_id: inst for inst in lighthouse.instances}

    baseline_ids = set(baseline_by_id)
    lighthouse_ids = set(lighthouse_by_id)
    if baseline_ids != lighthouse_ids:
        missing_from_lighthouse = sorted(baseline_ids - lighthouse_ids)
        missing_from_baseline = sorted(lighthouse_ids - baseline_ids)
        raise ValueError(
            "SWE-bench runs do not cover the same instance ids. "
            f"Missing from {lighthouse_label}: {missing_from_lighthouse or 'none'}. "
            f"Missing from {baseline_label}: {missing_from_baseline or 'none'}."
        )

    comparisons: list[SWEBenchInstanceComparison] = []
    improved = 0
    regressed = 0
    unchanged = 0

    for instance_id in sorted(baseline_ids):
        baseline_inst = baseline_by_id[instance_id]
        lighthouse_inst = lighthouse_by_id[instance_id]
        delta = _classify_delta(baseline_inst, lighthouse_inst)
        repo = (task_repo_map or {}).get(instance_id, "")

        if delta == "improved":
            improved += 1
        elif delta == "regressed":
            regressed += 1
        else:
            unchanged += 1

        comparisons.append(
            SWEBenchInstanceComparison(
                instance_id=instance_id,
                repo=repo,
                baseline_status=baseline_inst.status,
                lighthouse_status=lighthouse_inst.status,
                baseline_resolved=baseline_inst.resolved,
                lighthouse_resolved=lighthouse_inst.resolved,
                baseline_patch_exists=baseline_inst.patch_exists,
                lighthouse_patch_exists=lighthouse_inst.patch_exists,
                baseline_patch_successfully_applied=baseline_inst.patch_successfully_applied,
                lighthouse_patch_successfully_applied=lighthouse_inst.patch_successfully_applied,
                baseline_fail_to_pass_failures=len(
                    baseline_inst.fail_to_pass_failures
                ),
                lighthouse_fail_to_pass_failures=len(
                    lighthouse_inst.fail_to_pass_failures
                ),
                baseline_pass_to_pass_failures=len(
                    baseline_inst.pass_to_pass_failures
                ),
                lighthouse_pass_to_pass_failures=len(
                    lighthouse_inst.pass_to_pass_failures
                ),
                delta=delta,
            )
        )

    return SWEBenchRunComparison(
        baseline_label=baseline_label,
        lighthouse_label=lighthouse_label,
        baseline=baseline,
        lighthouse=lighthouse,
        improved_instances=improved,
        regressed_instances=regressed,
        unchanged_instances=unchanged,
        instance_comparisons=tuple(comparisons),
    )


def render_swebench_comparison_tables(comparison: SWEBenchRunComparison) -> str:
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
        "repo",
        f"{comparison.baseline_label}.status",
        f"{comparison.lighthouse_label}.status",
        f"{comparison.baseline_label}.resolved",
        f"{comparison.lighthouse_label}.resolved",
        f"{comparison.baseline_label}.patch_exists",
        f"{comparison.lighthouse_label}.patch_exists",
        f"{comparison.baseline_label}.FAIL_TO_PASS.failure",
        f"{comparison.lighthouse_label}.FAIL_TO_PASS.failure",
        f"{comparison.baseline_label}.PASS_TO_PASS.failure",
        f"{comparison.lighthouse_label}.PASS_TO_PASS.failure",
        "delta",
    )
    task_rows = [
        (
            inst.instance_id,
            inst.repo,
            inst.baseline_status,
            inst.lighthouse_status,
            _bool_cell(inst.baseline_resolved),
            _bool_cell(inst.lighthouse_resolved),
            _bool_cell(inst.baseline_patch_exists),
            _bool_cell(inst.lighthouse_patch_exists),
            str(inst.baseline_fail_to_pass_failures),
            str(inst.lighthouse_fail_to_pass_failures),
            str(inst.baseline_pass_to_pass_failures),
            str(inst.lighthouse_pass_to_pass_failures),
            inst.delta,
        )
        for inst in comparison.instance_comparisons
    ]

    summary_lines = [
        (
            "Outcome counts: "
            f"improved={comparison.improved_instances}, "
            f"regressed={comparison.regressed_instances}, "
            f"unchanged={comparison.unchanged_instances}"
        ),
        "",
        "Overall",
        _render_table(overall_headers, overall_rows),
        "",
        "Per-instance",
        _render_table(task_headers, task_rows),
    ]
    return "\n".join(summary_lines)


def build_swebench_score_rows(
    *,
    baseline: HarnessRunSummary,
    baseline_run_id: str,
    retrieval_runs: dict[str, tuple[HarnessRunSummary, str]],
) -> tuple[SWEBenchScoreRow, ...]:
    rows = [_score_row("baseline", baseline, baseline_run_id)]
    for label in ("code", "wiki"):
        entry = retrieval_runs.get(label)
        if entry is None:
            continue
        summary, run_id = entry
        rows.append(_score_row(label, summary, run_id))
    for label, (summary, run_id) in sorted(retrieval_runs.items()):
        if label in {"code", "wiki"}:
            continue
        rows.append(_score_row(label, summary, run_id))
    return tuple(rows)


def render_swebench_score_table(rows: Sequence[SWEBenchScoreRow]) -> str:
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


@dataclass(frozen=True)
class SWEBenchPassAtKInstanceRow:
    instance_id: str
    repo: str
    samples: int
    successes: int
    pass_at_k: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class SWEBenchPassAtKSummary:
    run_ids: tuple[str, ...]
    k_values: tuple[int, ...]
    instance_rows: tuple[SWEBenchPassAtKInstanceRow, ...]
    macro_pass_at_k: tuple[tuple[int, float], ...]


def compute_swebench_pass_at_k(
    *,
    run_summaries: Sequence[tuple[HarnessRunSummary, str]],
    k_values: Sequence[int],
    task_repo_map: Mapping[str, str] | None = None,
) -> SWEBenchPassAtKSummary:
    run_ids = tuple(run_id for _, run_id in run_summaries)
    k_vals = tuple(k_values)

    resolved_by_instance: dict[str, list[bool]] = {}
    for summary, _ in run_summaries:
        for inst in summary.instances:
            resolved_by_instance.setdefault(inst.instance_id, []).append(
                inst.resolved
            )

    instance_rows: list[SWEBenchPassAtKInstanceRow] = []
    for instance_id in sorted(resolved_by_instance):
        results = resolved_by_instance[instance_id]
        n = len(results)
        c = sum(results)
        repo = (task_repo_map or {}).get(instance_id, "")
        pass_at_k_values = tuple(
            (k, _pass_at_k_from_counts(n, c, k)) for k in k_vals
        )
        instance_rows.append(
            SWEBenchPassAtKInstanceRow(
                instance_id=instance_id,
                repo=repo,
                samples=n,
                successes=c,
                pass_at_k=pass_at_k_values,
            )
        )

    macro_pass_at_k: list[tuple[int, float]] = []
    for k in k_vals:
        if not instance_rows:
            macro_pass_at_k.append((k, 0.0))
            continue
        total = sum(
            dict(row.pass_at_k)[k] for row in instance_rows
        )
        macro_pass_at_k.append((k, total / len(instance_rows)))

    return SWEBenchPassAtKSummary(
        run_ids=run_ids,
        k_values=k_vals,
        instance_rows=tuple(instance_rows),
        macro_pass_at_k=tuple(macro_pass_at_k),
    )


def render_swebench_pass_at_k_table(summary: SWEBenchPassAtKSummary) -> str:
    headers = ("instance_id", "repo", "samples", "successes") + tuple(
        f"pass@{k}" for k in summary.k_values
    )
    rows: list[tuple[str, ...]] = []
    for row in summary.instance_rows:
        pass_at_k_cells = tuple(f"{v:.3f}" for _, v in row.pass_at_k)
        rows.append(
            (row.instance_id, row.repo, str(row.samples), str(row.successes))
            + pass_at_k_cells
        )

    macro_cells = tuple(f"{v:.3f}" for _, v in summary.macro_pass_at_k)
    rows.append(("MACRO", "", "", "") + macro_cells)

    return _render_table(headers, rows)


def _pass_at_k_from_counts(n: int, c: int, k: int) -> float:
    if n < k:
        return float(c > 0)
    if c == 0:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def _classify_delta(
    baseline: HarnessInstanceSummary,
    lighthouse: HarnessInstanceSummary,
) -> str:
    if lighthouse.resolved and not baseline.resolved:
        return "improved"
    if baseline.resolved and not lighthouse.resolved:
        return "regressed"
    b_failures = len(baseline.fail_to_pass_failures)
    l_failures = len(lighthouse.fail_to_pass_failures)
    if l_failures < b_failures:
        return "improved"
    if l_failures > b_failures:
        return "regressed"
    if lighthouse.status != baseline.status:
        if _status_rank(lighthouse.status) > _status_rank(baseline.status):
            return "improved"
        if _status_rank(lighthouse.status) < _status_rank(baseline.status):
            return "regressed"
    return "unchanged"


def _status_rank(status: str) -> int:
    ranks = {
        "missing_patch": 0,
        "patch_failed": 1,
        "unresolved": 2,
        "resolved": 3,
    }
    return ranks.get(status, -1)


def _score_row(
    label: str, summary: HarnessRunSummary, run_id: str
) -> SWEBenchScoreRow:
    total = summary.total_instances
    score_pct = 0.0 if total == 0 else (summary.resolved_instances / total) * 100.0
    return SWEBenchScoreRow(
        label=label,
        run_id=run_id,
        total_instances=summary.total_instances,
        resolved_instances=summary.resolved_instances,
        unresolved_instances=summary.unresolved_instances,
        score_pct=score_pct,
    )


def _signed_delta(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def _bool_cell(value: bool) -> str:
    return "true" if value else "false"


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
