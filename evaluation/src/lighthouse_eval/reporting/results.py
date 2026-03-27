"""Result aggregation and multi-track reporting."""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from lighthouse_eval.datasets.schema import (
    EvalResult,
    EvaluatorKind,
    MatchMetrics,
    RetrievalMetrics,
    TestExecutionMetrics,
)
from lighthouse_eval.reporting.tracks import (
    MatchSummary,
    RetrievalSummary,
    TestExecutionSummary,
)

log = logging.getLogger(__name__)


def _mean(vals: Sequence[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _stddev(vals: Sequence[float], mean: float | None = None) -> float:
    if len(vals) < 2:
        return 0.0
    m = mean if mean is not None else _mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def _ci_95(mean: float, stddev: float, n: int) -> tuple[float, float]:
    """Approximate 95% CI using t ~ 1.96 (large-sample approximation)."""
    if n < 2:
        return (mean, mean)
    margin = 1.96 * stddev / math.sqrt(n)
    return (mean - margin, mean + margin)


_GroupKey = tuple[str, str | None, str]  # (comparability_class, model, context_provider)
_GroupKey2 = tuple[str, str]  # (comparability_class, context_provider)


def _group_key(r: EvalResult) -> _GroupKey:
    return (r.provenance.comparability_class, r.model, r.context_provider)


def _aggregate_test_execution(
    results: list[EvalResult],
) -> list[TestExecutionSummary]:
    groups: dict[_GroupKey, list[EvalResult]] = defaultdict(list)
    for r in results:
        if r.evaluator_kind == EvaluatorKind.test_execution:
            groups[_group_key(r)].append(r)

    summaries: list[TestExecutionSummary] = []
    for (comp_class, model, provider), group in sorted(groups.items()):
        rates = [
            r.native_metrics.pass_rate
            for r in group
            if isinstance(r.native_metrics, TestExecutionMetrics)
        ]
        m = _mean(rates)
        sd = _stddev(rates, m)
        lo, hi = _ci_95(m, sd, len(rates))
        resolved = sum(1 for v in rates if v == 1.0)

        task_ids = {r.task_id for r in group}

        summaries.append(
            TestExecutionSummary(
                comparability_class=comp_class,
                model=model,
                context_provider=provider,
                num_tasks=len(task_ids),
                num_runs=len(rates),
                mean_pass_rate=m,
                stddev_pass_rate=sd,
                ci_95_lower=lo,
                ci_95_upper=hi,
                resolve_rate=resolved / len(rates) if rates else None,
            )
        )
    return summaries


def _aggregate_match(results: list[EvalResult]) -> list[MatchSummary]:
    groups: dict[_GroupKey, list[EvalResult]] = defaultdict(list)
    for r in results:
        if r.evaluator_kind == EvaluatorKind.match:
            groups[_group_key(r)].append(r)

    summaries: list[MatchSummary] = []
    for (comp_class, model, provider), group in sorted(groups.items()):
        metrics = [
            r.native_metrics
            for r in group
            if isinstance(r.native_metrics, MatchMetrics)
        ]

        exact_matches = [m.exact_match for m in metrics if m.exact_match is not None]
        edit_sims = [m.edit_similarity for m in metrics if m.edit_similarity is not None]
        bleus = [m.bleu_score for m in metrics if m.bleu_score is not None]

        em_rate = _mean([1.0 if v else 0.0 for v in exact_matches]) if exact_matches else None
        es_mean = _mean(edit_sims) if edit_sims else None
        es_sd = _stddev(edit_sims, es_mean) if edit_sims else None
        bleu_mean = _mean(bleus) if bleus else None
        bleu_sd = _stddev(bleus, bleu_mean) if bleus else None

        primary = edit_sims or [1.0 if v else 0.0 for v in exact_matches] or [0.0]
        pm = _mean(primary)
        psd = _stddev(primary, pm)
        lo, hi = _ci_95(pm, psd, len(primary))

        task_ids = {r.task_id for r in group}

        summaries.append(
            MatchSummary(
                comparability_class=comp_class,
                model=model,
                context_provider=provider,
                num_tasks=len(task_ids),
                num_runs=len(metrics),
                exact_match_rate=em_rate,
                mean_edit_similarity=es_mean,
                stddev_edit_similarity=es_sd,
                mean_bleu=bleu_mean,
                stddev_bleu=bleu_sd,
                ci_95_lower=lo,
                ci_95_upper=hi,
            )
        )
    return summaries


def _aggregate_retrieval(results: list[EvalResult]) -> list[RetrievalSummary]:
    # Retrieval summaries are grouped by (comparability_class, context_provider)
    # -- model is irrelevant since retrieval diagnostics score the provider.
    groups: dict[_GroupKey2, list[EvalResult]] = defaultdict(list)
    for r in results:
        if r.evaluator_kind == EvaluatorKind.retrieval_diagnostic:
            groups[(r.provenance.comparability_class, r.context_provider)].append(r)

    summaries: list[RetrievalSummary] = []
    for (comp_class, provider), group in sorted(groups.items()):
        metrics = [
            r.native_metrics
            for r in group
            if isinstance(r.native_metrics, RetrievalMetrics)
        ]

        precs = [m.precision_at_k for m in metrics if m.precision_at_k is not None]
        recs = [m.recall_at_k for m in metrics if m.recall_at_k is not None]
        mrrs = [m.mrr for m in metrics if m.mrr is not None]
        k_vals = [m.k for m in metrics]

        task_ids = {r.task_id for r in group}

        summaries.append(
            RetrievalSummary(
                comparability_class=comp_class,
                context_provider=provider,
                num_tasks=len(task_ids),
                num_runs=len(metrics),
                mean_precision_at_k=_mean(precs) if precs else None,
                stddev_precision_at_k=_stddev(precs) if precs else None,
                mean_recall_at_k=_mean(recs) if recs else None,
                stddev_recall_at_k=_stddev(recs) if recs else None,
                mean_mrr=_mean(mrrs) if mrrs else None,
                stddev_mrr=_stddev(mrrs) if mrrs else None,
                k=k_vals[0] if k_vals else 10,
            )
        )
    return summaries


def compute_deltas(
    summaries: list[TestExecutionSummary],
    baseline_provider: str = "none",
) -> list[dict[str, Any]]:
    """Compute per-model improvement over baseline for test-execution track."""
    by_class_model: dict[tuple[str, str], dict[str, TestExecutionSummary]] = defaultdict(dict)
    for s in summaries:
        by_class_model[(s.comparability_class, s.model)][s.context_provider] = s

    deltas: list[dict[str, Any]] = []
    for (comp_class, model), providers in sorted(by_class_model.items()):
        base = providers.get(baseline_provider)
        if base is None:
            continue
        for pname, summary in sorted(providers.items()):
            if pname == baseline_provider:
                continue
            deltas.append({
                "comparability_class": comp_class,
                "model": model,
                "baseline_provider": baseline_provider,
                "augmented_provider": pname,
                "baseline_mean_pass_rate": base.mean_pass_rate,
                "augmented_mean_pass_rate": summary.mean_pass_rate,
                "delta": summary.mean_pass_rate - base.mean_pass_rate,
            })
    return deltas


class EvalReport:
    """Aggregate all results into typed per-track summaries."""

    def __init__(self, results: list[EvalResult]) -> None:
        self.results = results
        self.test_execution = _aggregate_test_execution(results)
        self.match = _aggregate_match(results)
        self.retrieval = _aggregate_retrieval(results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_execution": [s.model_dump() for s in self.test_execution],
            "match": [s.model_dump() for s in self.match],
            "retrieval": [s.model_dump() for s in self.retrieval],
            "total_results": len(self.results),
        }

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        log.info("Report saved to %s", path)

    def save_markdown(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = _render_markdown(self)
        path.write_text("\n".join(lines), encoding="utf-8")
        log.info("Markdown report saved to %s", path)


def _render_markdown(report: EvalReport) -> list[str]:
    lines: list[str] = ["# Evaluation Report", ""]

    if report.test_execution:
        lines.append("## Test Execution")
        lines.append("")
        lines.append(
            "| Comparability Class | Model | Provider | Tasks | Runs "
            "| Mean Pass Rate | Stddev | 95% CI | Resolve Rate |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|---|---:|")
        for s in report.test_execution:
            rr = f"{s.resolve_rate:.2%}" if s.resolve_rate is not None else "-"
            lines.append(
                f"| {s.comparability_class} | {s.model} | {s.context_provider} "
                f"| {s.num_tasks} | {s.num_runs} "
                f"| {s.mean_pass_rate:.4f} | {s.stddev_pass_rate:.4f} "
                f"| [{s.ci_95_lower:.4f}, {s.ci_95_upper:.4f}] | {rr} |"
            )
        lines.append("")

    if report.match:
        lines.append("## Match")
        lines.append("")
        lines.append(
            "| Comparability Class | Model | Provider | Tasks | Runs "
            "| EM Rate | Mean Edit Sim | Mean BLEU | 95% CI |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---|")
        for s in report.match:
            em = f"{s.exact_match_rate:.4f}" if s.exact_match_rate is not None else "-"
            es = f"{s.mean_edit_similarity:.4f}" if s.mean_edit_similarity is not None else "-"
            bl = f"{s.mean_bleu:.4f}" if s.mean_bleu is not None else "-"
            lines.append(
                f"| {s.comparability_class} | {s.model} | {s.context_provider} "
                f"| {s.num_tasks} | {s.num_runs} "
                f"| {em} | {es} | {bl} "
                f"| [{s.ci_95_lower:.4f}, {s.ci_95_upper:.4f}] |"
            )
        lines.append("")

    if report.retrieval:
        lines.append("## Retrieval Diagnostics")
        lines.append("")
        lines.append(
            "| Comparability Class | Provider | Tasks | Runs "
            "| Mean P@k | Mean R@k | Mean MRR | k |"
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for s in report.retrieval:
            pk = f"{s.mean_precision_at_k:.4f}" if s.mean_precision_at_k is not None else "-"
            rk = f"{s.mean_recall_at_k:.4f}" if s.mean_recall_at_k is not None else "-"
            mr = f"{s.mean_mrr:.4f}" if s.mean_mrr is not None else "-"
            lines.append(
                f"| {s.comparability_class} | {s.context_provider} "
                f"| {s.num_tasks} | {s.num_runs} "
                f"| {pk} | {rk} | {mr} | {s.k} |"
            )
        lines.append("")

    lines.append(f"*Total results: {len(report.results)}*")
    lines.append("")
    return lines
