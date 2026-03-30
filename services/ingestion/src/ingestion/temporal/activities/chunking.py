from __future__ import annotations

import logging
import uuid
from pathlib import Path

from temporalio import activity

from ...chunking import (
    ASTCodeChunker,
    Chunker,
    ChunkerStrategy,
    SlidingWindowChunker,
    get_chunker,
)
from ...language import ExtensionLanguageDetector
from ...utilities.git_ops import GitOperations
from ...utilities.services import ChunkService
from .helpers import get_settings, make_db
from .inputs import ChunkFilesInput, ChunkFilesOutput

logger = logging.getLogger(__name__)


@activity.defn
async def chunk_files(input: ChunkFilesInput) -> ChunkFilesOutput:
    """Read files, chunk them, and write to the staging table."""
    settings = get_settings()
    db = make_db(settings)

    strategy = ChunkerStrategy(input.chunker_strategy)
    chunkers_by_language: dict[str | None, Chunker] = {}
    lang_detector = ExtensionLanguageDetector()
    repo_path = Path(input.repo_path)
    batch_id = str(uuid.uuid4())

    try:
        # Determine which files to process
        if input.file_filter is not None:
            files = [repo_path / f for f in input.file_filter if (repo_path / f).exists()]
        else:
            git = GitOperations(base_dir=settings.clone_base_dir)
            files = git.list_files(repo_path)

        all_chunks: list[dict] = []
        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                logger.warning("Could not read file: %s", file_path)
                continue

            if not content.strip():
                continue

            relative_path = str(file_path.relative_to(repo_path))
            language = lang_detector.detect(relative_path)

            chunker = chunkers_by_language.get(language)
            if chunker is None:
                if strategy is ChunkerStrategy.AST_CODE and language is None:
                    chunker = get_chunker(ChunkerStrategy.SLIDING_WINDOW)
                elif strategy is ChunkerStrategy.AST_CODE:
                    try:
                        chunker = get_chunker(strategy, language=language)
                    except Exception:
                        logger.exception(
                            "Chunker init failed for %s with strategy=%s and language=%s; "
                            "falling back to sliding_window",
                            relative_path,
                            strategy,
                            language,
                        )
                        chunker = get_chunker(ChunkerStrategy.SLIDING_WINDOW)
                else:
                    chunker = get_chunker(strategy, language=language)
                chunkers_by_language[language] = chunker

            try:
                if isinstance(chunker, ASTCodeChunker):
                    logger.info(
                        "Using AST chunker for %s (language=%s)",
                        relative_path,
                        language,
                    )
                elif (
                    strategy is ChunkerStrategy.AST_CODE
                    and isinstance(chunker, SlidingWindowChunker)
                ):
                    logger.info(
                        "Using fallback sliding_window chunker for %s "
                        "(AST requested but language detection unavailable)",
                        relative_path,
                    )
                chunk_results = chunker.chunk_file(content, relative_path, language=language)
            except Exception:
                logger.exception(
                    "Chunking failed for %s with strategy=%s; falling back to sliding_window",
                    relative_path,
                    strategy,
                )
                fallback = get_chunker(ChunkerStrategy.SLIDING_WINDOW)
                chunk_results = fallback.chunk_file(content, relative_path, language=language)

            for chunk in chunk_results:
                all_chunks.append(
                    {
                        "chunk_id": str(uuid.uuid4()),
                        "repository_id": input.repository_id,
                        "branch": input.branch,
                        "file_path": relative_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "content": chunk.content,
                        "language": language,
                        "chunk_hash": chunk.chunk_hash,
                    }
                )

        if not all_chunks:
            logger.info("No chunks to process")
            return ChunkFilesOutput(batch_id=batch_id, chunk_count=0)

        logger.info("Writing %d chunks to staging (batch %s)", len(all_chunks), batch_id)
        svc = ChunkService(db)
        svc.write_staging(batch_id, all_chunks)

        return ChunkFilesOutput(batch_id=batch_id, chunk_count=len(all_chunks))
    finally:
        db.close()
