from __future__ import annotations

from shared.config import CHUNK_MAX_LINES, CHUNK_OVERLAP_LINES

from .base_chunker import ChunkResult, Chunker
from .utils import compute_chunk_hash


class SlidingWindowChunker(Chunker):
    """Chunk code files using a sliding window with overlap."""

    def __init__(
        self,
        max_lines: int = CHUNK_MAX_LINES,
        overlap_lines: int = CHUNK_OVERLAP_LINES,
    ) -> None:
        self.max_lines = max_lines
        self.overlap_lines = overlap_lines

    def chunk_file(self, content: str, file_path: str) -> list[ChunkResult]:
        if not content.strip():
            return []

        lines = content.splitlines(keepends=True)
        total = len(lines)

        # If file fits in one chunk, return as-is
        if total <= self.max_lines:
            chunk_content = "".join(lines)
            return [
                ChunkResult(
                    content=chunk_content,
                    start_line=1,
                    end_line=total,
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
                    chunk_hash=compute_chunk_hash(chunk_content),
                )
            )

            if end >= total:
                break
            start += step

        return chunks
