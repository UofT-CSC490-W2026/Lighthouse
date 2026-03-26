from __future__ import annotations

import pytest

from ingestion.chunking.sliding_window_chunker import SlidingWindowChunker
from ingestion.chunking.base_chunker import ChunkResult
from ingestion.chunking.utils import compute_chunk_hash


@pytest.mark.unit
class TestSlidingWindowChunker:
    """Tests for SlidingWindowChunker."""

    def test_empty_string(self) -> None:
        chunker = SlidingWindowChunker()
        assert chunker.chunk_file("", "file.py") == []

    def test_whitespace_only(self) -> None:
        chunker = SlidingWindowChunker()
        assert chunker.chunk_file("   \n  ", "file.py") == []

    def test_single_line(self) -> None:
        chunker = SlidingWindowChunker()
        result = chunker.chunk_file("hello\n", "file.py")
        assert len(result) == 1
        assert result[0].start_line == 1
        assert result[0].end_line == 1
        assert result[0].content == "hello\n"
        assert result[0].chunk_hash == compute_chunk_hash("hello\n")

    def test_file_under_max_lines(self) -> None:
        chunker = SlidingWindowChunker()
        content = "".join(f"line {i}\n" for i in range(1, 11))
        result = chunker.chunk_file(content, "file.py")
        assert len(result) == 1
        assert result[0].start_line == 1
        assert result[0].end_line == 10
        assert result[0].content == content

    def test_file_exactly_max_lines(self) -> None:
        chunker = SlidingWindowChunker(max_lines=50, overlap_lines=10)
        content = "".join(f"line {i}\n" for i in range(1, 51))
        result = chunker.chunk_file(content, "file.py")
        assert len(result) == 1
        assert result[0].start_line == 1
        assert result[0].end_line == 50

    def test_file_over_max_lines(self) -> None:
        chunker = SlidingWindowChunker(max_lines=50, overlap_lines=10)
        content = "".join(f"line {i}\n" for i in range(1, 101))
        result = chunker.chunk_file(content, "file.py")

        assert len(result) == 3
        # First chunk: lines 1-50
        assert result[0].start_line == 1
        assert result[0].end_line == 50
        # Second chunk: lines 41-90
        assert result[1].start_line == 41
        assert result[1].end_line == 90
        # Third chunk: lines 81-100
        assert result[2].start_line == 81
        assert result[2].end_line == 100

    def test_overlap_content_shared(self) -> None:
        chunker = SlidingWindowChunker(max_lines=50, overlap_lines=10)
        lines = [f"line {i}\n" for i in range(1, 101)]
        content = "".join(lines)
        result = chunker.chunk_file(content, "file.py")

        # Lines 41-50 should appear in both chunk 0 and chunk 1
        overlap_content = "".join(lines[40:50])
        assert overlap_content in result[0].content
        assert overlap_content in result[1].content

    def test_chunk_hash_deterministic(self) -> None:
        chunker = SlidingWindowChunker()
        content = "".join(f"line {i}\n" for i in range(1, 11))
        result1 = chunker.chunk_file(content, "file.py")
        result2 = chunker.chunk_file(content, "file.py")
        assert result1[0].chunk_hash == result2[0].chunk_hash

    def test_chunk_hash_unique(self) -> None:
        chunker = SlidingWindowChunker()
        result1 = chunker.chunk_file("content A\n", "file.py")
        result2 = chunker.chunk_file("content B\n", "file.py")
        assert result1[0].chunk_hash != result2[0].chunk_hash

    def test_custom_params(self) -> None:
        chunker = SlidingWindowChunker(max_lines=20, overlap_lines=5)
        # step = 20 - 5 = 15
        # 40 lines: chunks at 1-20, 16-35, 31-40
        content = "".join(f"line {i}\n" for i in range(1, 41))
        result = chunker.chunk_file(content, "file.py")

        assert len(result) == 3
        assert result[0].start_line == 1
        assert result[0].end_line == 20
        assert result[1].start_line == 16
        assert result[1].end_line == 35
        assert result[2].start_line == 31
        assert result[2].end_line == 40

    def test_last_chunk_shorter(self) -> None:
        chunker = SlidingWindowChunker(max_lines=50, overlap_lines=10)
        content = "".join(f"line {i}\n" for i in range(1, 61))
        result = chunker.chunk_file(content, "file.py")

        assert len(result) == 2
        # First chunk: lines 1-50
        assert result[0].start_line == 1
        assert result[0].end_line == 50
        # Second chunk: lines 41-60
        assert result[1].start_line == 41
        assert result[1].end_line == 60
