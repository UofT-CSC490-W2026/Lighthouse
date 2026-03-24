from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChunkResult:
    """Result of chunking a single region of a file."""

    content: str
    start_line: int
    end_line: int
    language: str | None
    chunk_hash: str


class Chunker(ABC):
    """Abstract base class for code chunking strategies."""

    @abstractmethod
    def chunk_file(
        self, content: str, file_path: str, language: str | None = None
    ) -> list[ChunkResult]:
        ...
