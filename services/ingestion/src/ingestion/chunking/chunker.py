from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from shared.config import CHUNK_MAX_LINES, CHUNK_OVERLAP_LINES

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
    ".r": "r",
    ".lua": "lua",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".clj": "clojure",
    ".vim": "vim",
    ".proto": "protobuf",
    ".tf": "terraform",
    ".dockerfile": "dockerfile",
}


def detect_language(file_path: str) -> str | None:
    """Detect programming language from file extension."""
    name = Path(file_path).name.lower()
    if name == "dockerfile":
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    suffix = Path(file_path).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(suffix)


def compute_chunk_hash(content: str) -> str:
    """Compute SHA-256 hash of chunk content for dedup."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class ChunkResult:
    """Result of chunking a single region of a file."""

    content: str
    start_line: int
    end_line: int
    language: str | None
    chunk_hash: str


class CodeChunker(ABC):
    """Abstract base class for code chunking strategies."""

    @abstractmethod
    def chunk_file(
        self, content: str, file_path: str, language: str | None = None
    ) -> list[ChunkResult]:
        ...


class SlidingWindowChunker(CodeChunker):
    """Chunk code files using a sliding window with overlap."""

    def __init__(
        self,
        max_lines: int = CHUNK_MAX_LINES,
        overlap_lines: int = CHUNK_OVERLAP_LINES,
    ) -> None:
        self.max_lines = max_lines
        self.overlap_lines = overlap_lines

    def chunk_file(
        self, content: str, file_path: str, language: str | None = None
    ) -> list[ChunkResult]:
        if not content.strip():
            return []

        lang = language or detect_language(file_path)
        lines = content.splitlines(keepends=True)
        total = len(lines)

        if total == 0:
            return []

        # If file fits in one chunk, return as-is
        if total <= self.max_lines:
            chunk_content = "".join(lines)
            return [
                ChunkResult(
                    content=chunk_content,
                    start_line=1,
                    end_line=total,
                    language=lang,
                    chunk_hash=compute_chunk_hash(chunk_content),
                )
            ]

        chunks: list[ChunkResult] = []
        step = self.max_lines - self.overlap_lines
        start = 0

        while start < total:
            end = min(start + self.max_lines, total)
            chunk_lines = lines[start:end]
            chunk_content = "".join(chunk_lines)

            chunks.append(
                ChunkResult(
                    content=chunk_content,
                    start_line=start + 1,  # 1-indexed
                    end_line=end,
                    language=lang,
                    chunk_hash=compute_chunk_hash(chunk_content),
                )
            )

            if end >= total:
                break
            start += step

        return chunks
