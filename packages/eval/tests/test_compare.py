from __future__ import annotations

import pytest

from eval.compare import (
    SWEBenchRunComparison,
    build_swebench_score_rows,
    compare_swebench_runs,
    compute_swebench_pass_at_k,
    render_swebench_comparison_tables,
    render_swebench_pass_at_k_table,
    render_swebench_score_table,
)
from eval.harness import HarnessEvaluationResult
from eval.summary import HarnessInstanceSummary, HarnessRunSummary

from pathlib import Path


def _make_instance(
    instance_id: str,
    *,
    resolved: bool = False,
    patch_exists: bool = True,
    patch_applied: bool = True,
    f2p_successes: tuple[str, ...] = (),
    f2p_failures: tuple[str, ...] = (),
    p2p_failures: tuple[str, ...] = (),
) -> HarnessInstanceSummary:
    return HarnessInstanceSummary(
        instance_id=instance_id,
        resolved=resolved,
        patch_exists=patch_exists,
        patch_successfully_applied=patch_applied,
        fail_to_pass_successes=f2p_successes,
        fail_to_pass_failures=f2p_failures,
        pass_to_pass_failures=p2p_failures,
    )


def _make_summary(
    instances: tuple[HarnessInstanceSummary, ...],
    *,
    total: int | None = None,
    resolved: int | None = None,
) -> HarnessRunSummary:
    total_instances = total if total is not None else len(instances)
    resolved_instances = (
        resolved
        if resolved is not None
        else sum(1 for i in instances if i.resolved)
    )
    unresolved = total_instances - resolved_instances
    empty_patch = sum(1 for i in instances if not i.patch_exists)
    return HarnessRunSummary(
        outputs=HarnessEvaluationResult(
            report_path=Path("/tmp/report.json"),
            run_log_dir=Path("/tmp/logs"),
        ),
        total_instances=total_instances,
        submitted_instances=total_instances,
        completed_instances=total_instances,
        resolved_instances=resolved_instances,
        unresolved_instances=unresolved,
        empty_patch_instances=empty_patch,
        error_instances=0,
        instances=instances,
    )


@pytest.mark.unit
def test_compare_classifies_improvement_and_regression() -> None:
    baseline = _make_summary(
        (
            _make_instance("django__django-11001", resolved=False, f2p_failures=("t1",)),
            _make_instance("sympy__sympy-20001", resolved=True),
        ),
    )
    lighthouse = _make_summary(
        (
            _make_instance("django__django-11001", resolved=True),
            _make_instance("sympy__sympy-20001", resolved=False, f2p_failures=("t2",)),
        ),
    )

    comparison = compare_swebench_runs(
        baseline=baseline,
        lighthouse=lighthouse,
        baseline_run_id="base",
        lighthouse_run_id="lh",
        task_repo_map={
            "django__django-11001": "django/django",
            "sympy__sympy-20001": "sympy/sympy",
        },
    )

    assert comparison.improved_instances == 1
    assert comparison.regressed_instances == 1
    assert comparison.unchanged_instances == 0
    assert comparison.instance_comparisons[0].delta == "improved"
    assert comparison.instance_comparisons[0].repo == "django/django"
    assert comparison.instance_comparisons[1].delta == "regressed"


@pytest.mark.unit
def test_compare_unchanged_when_both_resolved() -> None:
    baseline = _make_summary(
        (_make_instance("django__django-11001", resolved=True),),
    )
    lighthouse = _make_summary(
        (_make_instance("django__django-11001", resolved=True),),
    )

    comparison = compare_swebench_runs(
        baseline=baseline,
        lighthouse=lighthouse,
        baseline_run_id="base",
        lighthouse_run_id="lh",
    )

    assert comparison.unchanged_instances == 1
    assert comparison.instance_comparisons[0].delta == "unchanged"


@pytest.mark.unit
def test_compare_mismatched_instance_ids_raises() -> None:
    baseline = _make_summary(
        (_make_instance("django__django-11001"),),
    )
    lighthouse = _make_summary(
        (_make_instance("sympy__sympy-20001"),),
    )

    with pytest.raises(ValueError, match="do not cover the same instance ids"):
        compare_swebench_runs(
            baseline=baseline,
            lighthouse=lighthouse,
            baseline_run_id="base",
            lighthouse_run_id="lh",
        )


@pytest.mark.unit
def test_render_comparison_tables_includes_sections() -> None:
    baseline = _make_summary(
        (_make_instance("django__django-11001", resolved=False, f2p_failures=("t1",)),),
    )
    lighthouse = _make_summary(
        (_make_instance("django__django-11001", resolved=True),),
    )

    comparison = compare_swebench_runs(
        baseline=baseline,
        lighthouse=lighthouse,
        baseline_run_id="base",
        lighthouse_run_id="lh",
        baseline_label="base",
        lighthouse_label="lh",
    )
    text = render_swebench_comparison_tables(comparison)

    assert "Overall" in text
    assert "Per-instance" in text
    assert "base" in text
    assert "lh" in text
    assert "django__django-11001" in text
    assert "improved" in text
    assert "submitted_instances" in text


@pytest.mark.unit
def test_score_table_renders_percentages() -> None:
    baseline = _make_summary(
        (
            _make_instance("a", resolved=True),
            _make_instance("b", resolved=False),
        ),
    )
    lighthouse_code = _make_summary(
        (
            _make_instance("a", resolved=True),
            _make_instance("b", resolved=True),
        ),
    )

    rows = build_swebench_score_rows(
        baseline=baseline,
        baseline_run_id="base-run",
        retrieval_runs={"code": (lighthouse_code, "code-run")},
    )
    text = render_swebench_score_table(rows)

    assert "50.0%" in text
    assert "100.0%" in text
    assert "baseline" in text
    assert "code" in text


@pytest.mark.unit
def test_pass_at_k_with_two_runs() -> None:
    run1 = _make_summary(
        (
            _make_instance("a", resolved=True),
            _make_instance("b", resolved=False),
        ),
    )
    run2 = _make_summary(
        (
            _make_instance("a", resolved=True),
            _make_instance("b", resolved=True),
        ),
    )

    summary = compute_swebench_pass_at_k(
        run_summaries=[(run1, "run1"), (run2, "run2")],
        k_values=[1, 2],
        task_repo_map={"a": "django/django", "b": "sympy/sympy"},
    )

    assert summary.run_ids == ("run1", "run2")
    assert summary.k_values == (1, 2)
    assert len(summary.instance_rows) == 2

    # Instance "a": 2 samples, 2 successes → pass@1=1.0, pass@2=1.0
    row_a = next(r for r in summary.instance_rows if r.instance_id == "a")
    assert row_a.samples == 2
    assert row_a.successes == 2
    assert dict(row_a.pass_at_k)[1] == 1.0
    assert dict(row_a.pass_at_k)[2] == 1.0

    # Instance "b": 2 samples, 1 success → pass@1=0.5, pass@2=1.0
    row_b = next(r for r in summary.instance_rows if r.instance_id == "b")
    assert row_b.samples == 2
    assert row_b.successes == 1
    assert dict(row_b.pass_at_k)[1] == pytest.approx(0.5)
    assert dict(row_b.pass_at_k)[2] == 1.0

    # Macro: pass@1 = (1.0 + 0.5)/2 = 0.75
    macro = dict(summary.macro_pass_at_k)
    assert macro[1] == pytest.approx(0.75)
    assert macro[2] == pytest.approx(1.0)


@pytest.mark.unit
def test_pass_at_k_table_renders() -> None:
    run1 = _make_summary(
        (_make_instance("a", resolved=True),),
    )

    summary = compute_swebench_pass_at_k(
        run_summaries=[(run1, "run1")],
        k_values=[1],
    )
    text = render_swebench_pass_at_k_table(summary)

    assert "pass@1" in text
    assert "MACRO" in text
    assert "1.000" in text
