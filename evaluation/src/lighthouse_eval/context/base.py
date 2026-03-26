from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from lighthouse_eval.datasets.schema import Task


class ContextSnippet(BaseModel):
    """A single piece of retrieved context (code, doc, etc.)."""

    file_path: str
    content: str
    start_line: int | None = None
    end_line: int | None = None
    language: str | None = None
    score: float = 0.0
    reason: str | None = None


@runtime_checkable
class ContextProvider(Protocol):
    """Pluggable source of context injected alongside a task prompt."""

    name: str

    async def get_context(self, task: Task) -> list[ContextSnippet]: ...
