from __future__ import annotations

import hashlib
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


def _stable_gold_id(gold: ContextSnippetRef, index: int) -> str:
    if gold.snippet_id:
        return gold.snippet_id
    digest = hashlib.sha1(gold.content.encode("utf-8")).hexdigest()
    return f"{gold.file_path}:{gold.start_line}:{gold.end_line}:{digest}:{index}"


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

        gold_snippets = list(spec.ground_truth_snippets)
        for index in spec.gold_indices:
            if 0 <= index < len(task.oracle_context):
                gold_snippets.append(task.oracle_context[index])

        gold_by_id: dict[str, ContextSnippetRef] = {}
        for index, gold in enumerate(gold_snippets):
            gold_by_id[_stable_gold_id(gold, index)] = gold

        k = spec.k
        retrieved = self._last_context[:k]
        num_gold = len(gold_by_id)

        if num_gold == 0:
            return RetrievalMetrics(
                k=k, num_gold_snippets=0, num_retrieved=len(retrieved),
            )

        matched_gold_ids: set[str] = set()
        first_hit_rank: int | None = None
        for rank, retrieved_snippet in enumerate(retrieved, start=1):
            matching_ids = {
                gold_id
                for gold_id, gold in gold_by_id.items()
                if _snippet_matches(retrieved_snippet, gold)
            }
            if matching_ids and first_hit_rank is None:
                first_hit_rank = rank
            matched_gold_ids.update(matching_ids)

        num_hits = len(matched_gold_ids)
        precision = num_hits / k if k > 0 else 0.0
        recall = min(num_hits / num_gold if num_gold > 0 else 0.0, 1.0)

        mrr = 0.0
        if first_hit_rank is not None:
            mrr = 1.0 / first_hit_rank

        return RetrievalMetrics(
            precision_at_k=precision,
            recall_at_k=recall,
            mrr=mrr,
            k=k,
            num_gold_snippets=num_gold,
            num_retrieved=len(retrieved),
        )
