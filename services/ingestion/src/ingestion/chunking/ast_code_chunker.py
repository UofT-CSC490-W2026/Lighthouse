from __future__ import annotations

import logging
from pathlib import Path

from astchunk import ASTChunkBuilder

from ..language.detector import EXTENSION_TO_LANGUAGE
from .base_chunker import ChunkResult, Chunker
from .utils import compute_chunk_hash

logger = logging.getLogger(__name__)


class ASTCodeChunker(Chunker):
    """
    Chunk code files using AST-aware chunk boundaries.

    Implementation sourrced from https://github.com/yilinjz/astchunk
    """

    def __init__(
        self,
        language: str | None = None,
        max_chunk_size: int = 500,
        metadata_template: str = "default",
    ) -> None:
        self.default_language = language
        self.max_chunk_size = max_chunk_size
        self.metadata_template = metadata_template
        self.ast_builders: dict[str, ASTChunkBuilder] = {}

        if language is not None:
            self.ast_builders[language] = self._make_builder(language)

    def _make_builder(self, language: str) -> ASTChunkBuilder:
        return ASTChunkBuilder(
            language=language,
            max_chunk_size=self.max_chunk_size,
            metadata_template=self.metadata_template,
        )

    def _detect_language_from_path(self, file_path: str) -> str | None:
        path = Path(file_path)
        name = path.name.lower()
        if name == "dockerfile":
            return "dockerfile"
        if name == "makefile":
            return "makefile"
        return EXTENSION_TO_LANGUAGE.get(path.suffix.lower())

    def chunk_file(
        self, content: str, file_path: str, language: str | None = None
    ) -> list[ChunkResult]:
        if not content.strip():
            return []

        resolved_language = (
            language or self.default_language or self._detect_language_from_path(file_path)
        )
        if resolved_language is None:
            raise ValueError(
                f"Could not infer language for AST chunking from file path: {file_path}"
            )

        logger.info(
            "Chunking %s with AST chunker (language=%s)", file_path, resolved_language
        )

        ast_builder = self.ast_builders.get(resolved_language)
        if ast_builder is None:
            ast_builder = self._make_builder(resolved_language)
            self.ast_builders[resolved_language] = ast_builder

        ast_builder_chunks = ast_builder.chunkify(content)

        chunks: list[ChunkResult] = []

        for chunk in ast_builder_chunks:
            chunk_content = chunk["content"]
            metadata = chunk["metadata"]

            start_line = metadata["start_line_no"]
            end_line = metadata["end_line_no"]

            chunks.append(
                ChunkResult(
                    content=chunk_content,
                    start_line=start_line + 1,  # 1-indexed
                    end_line=end_line,
                    language=resolved_language,
                    chunk_hash=compute_chunk_hash(chunk_content),
                )
            )

        return chunks
