from __future__ import annotations

import pytest

from ingestion.chunking.ast_code_chunker import ASTCodeChunker
from ingestion.chunking.utils import compute_chunk_hash


class FakeASTChunkBuilder:
    created_languages: list[str] = []

    def __init__(
        self, language: str, max_chunk_size: int, metadata_template: str
    ) -> None:
        self.language = language
        self.max_chunk_size = max_chunk_size
        self.metadata_template = metadata_template
        self.chunkify_calls = 0
        FakeASTChunkBuilder.created_languages.append(language)

    def chunkify(self, content: str) -> list[dict]:
        self.chunkify_calls += 1
        return [
            {
                "content": content,
                "metadata": {"start_line_no": 0, "end_line_no": content.count("\n")},
            }
        ]


@pytest.mark.unit
class TestASTCodeChunker:
    def setup_method(self) -> None:
        FakeASTChunkBuilder.created_languages = []

    def test_empty_content_returns_no_chunks(self) -> None:
        chunker = ASTCodeChunker()
        assert chunker.chunk_file("", "file.py") == []

    def test_detects_language_from_extension(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "ingestion.chunking.ast_code_chunker.ASTChunkBuilder",
            FakeASTChunkBuilder,
        )
        chunker = ASTCodeChunker()

        result = chunker.chunk_file("print('ok')\n", "src/main.py")

        assert FakeASTChunkBuilder.created_languages == ["python"]
        assert len(result) == 1
        assert result[0].start_line == 1
        assert result[0].end_line == 1
        assert result[0].content == "print('ok')\n"
        assert result[0].chunk_hash == compute_chunk_hash("print('ok')\n")

    def test_explicit_language_overrides_extension(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "ingestion.chunking.ast_code_chunker.ASTChunkBuilder",
            FakeASTChunkBuilder,
        )
        chunker = ASTCodeChunker()

        chunker.chunk_file("const x = 1;\n", "src/main.py", language="javascript")

        assert FakeASTChunkBuilder.created_languages == ["javascript"]

    def test_uses_default_language_when_extension_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "ingestion.chunking.ast_code_chunker.ASTChunkBuilder",
            FakeASTChunkBuilder,
        )
        chunker = ASTCodeChunker(language="python")

        chunker.chunk_file("print('ok')\n", "README.unknown")

        assert FakeASTChunkBuilder.created_languages == ["python"]

    def test_raises_when_language_cannot_be_inferred(self) -> None:
        chunker = ASTCodeChunker()

        with pytest.raises(ValueError, match="Could not infer language"):
            chunker.chunk_file("content\n", "README.unknown")

    def test_reuses_cached_builder_per_language(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "ingestion.chunking.ast_code_chunker.ASTChunkBuilder",
            FakeASTChunkBuilder,
        )
        chunker = ASTCodeChunker()

        chunker.chunk_file("print('one')\n", "a.py")
        chunker.chunk_file("print('two')\n", "b.py")

        assert FakeASTChunkBuilder.created_languages == ["python"]
