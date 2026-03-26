from __future__ import annotations

import logging
import uuid
from pathlib import Path

from temporalio import activity

from ...chunking import ChunkerStrategy, get_chunker
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

    chunker = get_chunker(ChunkerStrategy(input.chunker_strategy))
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
            chunk_results = chunker.chunk_file(content, relative_path)

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
