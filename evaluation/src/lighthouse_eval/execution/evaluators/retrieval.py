from __future__ import annotations

from pathlib import Path

from lighthouse_eval.candidates.base import _CandidateBase
from lighthouse_eval.context.base import ContextSnippet
from lighthouse_eval.datasets.schema import (
    ContextSnippetRef,
    EvaluatorKind,
    RetrievalMetrics,
    Task,
)


def _snippet_matches(retrieved: ContextSnippet, gold: ContextSnippetRef) -> bool:
    """Determine if a retrieved snippet matches a gold snippet.

    Uses file_path + content overlap as the matching criterion.
    """
    if retrieved.file_path != gold.file_path:
        return False
    return gold.content.strip() in retrieved.content.strip()


class RetrievalDiagnosticEvaluator:
    """Measure retrieval quality against known gold snippets.

    Unlike other evaluators, this one scores the *context provider* rather than
    the generated code.  The ``candidate`` argument is unused; scoring is based
    on ``retrieved_context`` passed separately.
    """

    kind = EvaluatorKind.retrieval_diagnostic

    def __init__(self) -> None:
        self._last_context: list[ContextSnippet] = []

    def set_retrieved_context(self, ctx: list[ContextSnippet]) -> None:
        """Inject the context that was actually retrieved (called by the runner)."""
        self._last_context = ctx

    async def evaluate(
        self, task: Task, candidate: _CandidateBase, workspace: Path
    ) -> RetrievalMetrics:
        spec = task.retrieval_spec
        if spec is None:
            raise ValueError(f"Task {task.id} has no retrieval_spec")

        gold_snippets = spec.ground_truth_snippets
        k = spec.k
        retrieved = self._last_context[:k]
        num_gold = len(gold_snippets)

        if num_gold == 0:
            return RetrievalMetrics(
                k=k, num_gold_snippets=0, num_retrieved=len(retrieved),
            )

        hits_at_rank: list[bool] = []
        for r in retrieved:
            hits_at_rank.append(
                any(_snippet_matches(r, g) for g in gold_snippets)
            )

        num_hits = sum(hits_at_rank)
        precision = num_hits / k if k > 0 else 0.0
        recall = num_hits / num_gold if num_gold > 0 else 0.0

        mrr = 0.0
        for i, hit in enumerate(hits_at_rank):
            if hit:
                mrr = 1.0 / (i + 1)
                break

        return RetrievalMetrics(
            precision_at_k=precision,
            recall_at_k=recall,
            mrr=mrr,
            k=k,
            num_gold_snippets=num_gold,
            num_retrieved=len(retrieved),
        )
