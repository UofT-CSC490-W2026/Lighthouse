"""Per-track summary models.

Each track (test-execution, match, retrieval) has its own summary type that
is never mixed with the others.  Every summary carries ``comparability_class``
so results from different datasets are never inadvertently aggregated.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TestExecutionSummary(BaseModel):
    """Aggregate stats for test-execution evaluations."""

    comparability_class: str
    model: str
    context_provider: str
    num_tasks: int = 0
    num_runs: int = 0
    mean_pass_rate: float = 0.0
    stddev_pass_rate: float = 0.0
    ci_95_lower: float = 0.0
    ci_95_upper: float = 0.0
    resolve_rate: float | None = Field(
        default=None,
        description="Fraction of tasks where pass_rate == 1.0 (fully resolved).",
    )


class MatchSummary(BaseModel):
    """Aggregate stats for match-based evaluations."""

    comparability_class: str
    model: str
    context_provider: str
    num_tasks: int = 0
    num_runs: int = 0
    exact_match_rate: float | None = None
    mean_edit_similarity: float | None = None
    stddev_edit_similarity: float | None = None
    mean_bleu: float | None = None
    stddev_bleu: float | None = None
    ci_95_lower: float = 0.0
    ci_95_upper: float = 0.0


class RetrievalSummary(BaseModel):
    """Aggregate stats for retrieval diagnostic evaluations."""

    comparability_class: str
    context_provider: str
    num_tasks: int = 0
    num_runs: int = 0
    mean_precision_at_k: float | None = None
    stddev_precision_at_k: float | None = None
    mean_recall_at_k: float | None = None
    stddev_recall_at_k: float | None = None
    mean_mrr: float | None = None
    stddev_mrr: float | None = None
    k: int = 10
