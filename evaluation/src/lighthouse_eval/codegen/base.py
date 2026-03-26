from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from lighthouse_eval.candidates import CandidateEdit
    from lighthouse_eval.context.base import ContextSnippet
    from lighthouse_eval.datasets.schema import Task


@runtime_checkable
class CodeGenerator(Protocol):
    """Wraps an LLM to produce candidate edits for a task."""

    model_name: str

    async def generate(
        self, task: Task, context: list[ContextSnippet]
    ) -> CandidateEdit: ...
