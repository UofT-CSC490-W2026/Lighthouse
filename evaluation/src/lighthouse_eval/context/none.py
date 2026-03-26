from __future__ import annotations

from lighthouse_eval.context.base import ContextSnippet
from lighthouse_eval.datasets.schema import Task


class NoneProvider:
    """Baseline context provider — returns no context."""

    name: str = "none"

    async def get_context(self, task: Task) -> list[ContextSnippet]:
        return []
