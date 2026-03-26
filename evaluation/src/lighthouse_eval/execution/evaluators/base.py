from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from lighthouse_eval.datasets.schema import (
    EvaluatorKind,
    MatchMetrics,
    RetrievalMetrics,
    TestExecutionMetrics,
)

if TYPE_CHECKING:
    from lighthouse_eval.candidates import CandidateEdit
    from lighthouse_eval.datasets.schema import Task

NativeMetrics = TestExecutionMetrics | MatchMetrics | RetrievalMetrics


@runtime_checkable
class Evaluator(Protocol):
    """Scores a candidate edit against a task specification."""

    kind: EvaluatorKind

    async def evaluate(
        self, task: Task, candidate: CandidateEdit, workspace: Path
    ) -> NativeMetrics: ...
