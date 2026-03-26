"""Workspace materialisation and evaluator dispatch."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from lighthouse_eval.candidates.base import (
    Completion,
    FileRewrite,
    MultiFileRewrite,
    UnifiedPatch,
    _CandidateBase,
)
from lighthouse_eval.context.base import ContextSnippet
from lighthouse_eval.datasets.schema import (
    EvaluatorKind,
    Task,
)
from lighthouse_eval.execution.evaluators.match import (
    BLEUEvaluator,
    EditSimilarityEvaluator,
    ExactMatchEvaluator,
)
from lighthouse_eval.execution.evaluators.retrieval import RetrievalDiagnosticEvaluator
from lighthouse_eval.execution.evaluators.test_execution import PytestEvaluator

log = logging.getLogger(__name__)


def create_workspace(task: Task) -> Path:
    """Create a temporary workspace directory for a single evaluation run.

    If ``task.workspace_path`` points to an existing directory it is copied;
    otherwise an empty temp directory is returned.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"lheval_{task.id}_"))

    if task.workspace_path and task.workspace_path.is_dir():
        shutil.copytree(task.workspace_path, tmp, dirs_exist_ok=True)

    return tmp


def cleanup_workspace(workspace: Path) -> None:
    """Remove a workspace created by :func:`create_workspace`."""
    try:
        shutil.rmtree(workspace)
    except OSError as exc:
        log.warning("Failed to clean up workspace %s: %s", workspace, exc)


def serialize_candidate(candidate: _CandidateBase) -> dict[str, str]:
    """Convert a candidate edit into a JSON-friendly dict for storage."""
    if isinstance(candidate, FileRewrite):
        return {candidate.filename: candidate.content}
    if isinstance(candidate, MultiFileRewrite):
        return dict(candidate.files)
    if isinstance(candidate, UnifiedPatch):
        return {"_patch": candidate.diff}
    if isinstance(candidate, Completion):
        return {"_completion": candidate.text}
    return {"_raw": str(candidate)}


def resolve_evaluator(
    task: Task,
    retrieved_context: list[ContextSnippet] | None = None,
):
    """Return the correct evaluator instance for *task.evaluator_kind*.

    For match-based tasks the concrete evaluator is chosen by
    ``task.match_spec.metric``.  For retrieval diagnostics the retrieved
    context is injected before returning.
    """
    if task.evaluator_kind == EvaluatorKind.test_execution:
        return PytestEvaluator()

    if task.evaluator_kind == EvaluatorKind.match:
        metric = "exact_match"
        if task.match_spec is not None:
            metric = task.match_spec.metric
        if metric == "bleu":
            return BLEUEvaluator()
        if metric == "edit_similarity":
            return EditSimilarityEvaluator()
        return ExactMatchEvaluator()

    if task.evaluator_kind == EvaluatorKind.retrieval_diagnostic:
        evaluator = RetrievalDiagnosticEvaluator()
        if retrieved_context is not None:
            evaluator.set_retrieved_context(retrieved_context)
        return evaluator

    raise ValueError(f"Unknown evaluator_kind: {task.evaluator_kind}")
