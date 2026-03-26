from __future__ import annotations

from lighthouse_eval.context.base import ContextSnippet
from lighthouse_eval.datasets.schema import Task


class StaticProvider:
    """Serves pre-baked oracle context from ``task.oracle_context``.

    Used for ablation studies where a dataset ships ground-truth cross-file
    context (e.g. CrossCodeEval, RepoBench).
    """

    name: str = "static:oracle"

    def __init__(self, *, name: str = "static:oracle") -> None:
        self.name = name

    async def get_context(self, task: Task) -> list[ContextSnippet]:
        return [
            ContextSnippet(
                file_path=ref.file_path,
                content=ref.content,
                start_line=ref.start_line,
                end_line=ref.end_line,
            )
            for ref in task.oracle_context
        ]
