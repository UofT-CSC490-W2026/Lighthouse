from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from temporalio import activity

from ..chunking import ChunkerStrategy, get_chunker
from ..embedding import EmbeddingStrategy, get_embedding_provider
from ..language import ExtensionLanguageDetector
from ..utilities.config import IngestionSettings
from ..utilities.git_ops import GitOperations
from ..utilities.services import BranchService, ChunkService, RepositoryService

from db import DatabaseManager
from shared.config import EMBEDDING_DIMENSION, MILVUS_COLLECTION_NAME
from vectordb import MilvusClient

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 512


# --- Input / Output dataclasses ---


@dataclass
class EnsureRepoInput:
    github_repo_id: int
    repo_url: str
    full_name: str


@dataclass
class UpdateBranchStatusInput:
    repository_id: str
    branch: str
    status: str
    latest_commit: str | None = None
    github_token: str | None = None


@dataclass
class GitCloneFetchInput:
    repo_url: str
    repo_dir_name: str
    branch: str
    github_token: str | None = None


@dataclass
class GitCloneFetchOutput:
    repo_path: str
    latest_commit: str


@dataclass
class ChunkFilesInput:
    repo_path: str
    repository_id: str
    branch: str
    chunker_strategy: str = "sliding_window"
    file_filter: list[str] | None = None


@dataclass
class ChunkFilesOutput:
    batch_id: str
    chunk_count: int


@dataclass
class GetChangedFilesInput:
    repo_path: str
    before_commit: str
    after_commit: str


@dataclass
class DeleteChunksInput:
    repository_id: str
    branch: str


@dataclass
class DeleteChunksForFilesInput:
    repository_id: str
    branch: str
    file_paths: list[str] = field(default_factory=list)


@dataclass
class EmbedBatchInput:
    batch_id: str
    offset: int
    limit: int
    embedding_strategy: str = "openai"


@dataclass
class StoreChunksInput:
    batch_id: str


@dataclass
class CleanupStagingInput:
    batch_id: str


# --- Workflow-level input dataclasses (used by main.py to start workflows) ---


@dataclass
class IndexRepoInput:
    github_repo_id: int
    repo_url: str
    full_name: str
    branches: list[str]
    github_token: str | None = None


@dataclass
class IndexBranchInput:
    repository_id: str
    github_repo_id: int
    repo_url: str
    full_name: str
    branch: str
    github_token: str | None = None
    chunker_strategy: str = "sliding_window"
    embedding_strategy: str = "openai"


@dataclass
class IncrementalIndexInput:
    github_repo_id: int
    full_name: str
    branch: str
    before_commit: str
    after_commit: str


# --- Helper to build DB/Milvus connections per activity ---


def _make_db(settings: IngestionSettings) -> DatabaseManager:
    db = DatabaseManager(settings.postgres_dsn)
    db.connect()
    return db


def _make_milvus(settings: IngestionSettings) -> MilvusClient:
    milvus = MilvusClient(
        uri=settings.milvus_uri,
        collection_name=MILVUS_COLLECTION_NAME,
    )
    milvus.ensure_collection(dimension=EMBEDDING_DIMENSION)
    return milvus


# --- Activities ---


@activity.defn
async def ensure_repository_record(input: EnsureRepoInput) -> str:
    """Upsert a Repository row and return its id."""
    settings = IngestionSettings()
    db = _make_db(settings)
    try:
        svc = RepositoryService(db)
        return svc.ensure(input.github_repo_id, input.repo_url, input.full_name)
    finally:
        db.close()


@activity.defn
async def update_branch_status(input: UpdateBranchStatusInput) -> str:
    """Update the IndexedBranch status."""
    settings = IngestionSettings()
    db = _make_db(settings)
    try:
        svc = BranchService(db)
        return svc.update_status(
            repository_id=input.repository_id,
            branch=input.branch,
            status=input.status,
            latest_commit=input.latest_commit,
            github_token=input.github_token,
        )
    finally:
        db.close()


@activity.defn
async def git_clone_or_fetch(input: GitCloneFetchInput) -> GitCloneFetchOutput:
    """Clone or fetch a repo and return the path + latest commit."""
    settings = IngestionSettings()
    git = GitOperations(
        base_dir=settings.clone_base_dir,
        github_token=input.github_token,
    )
    repo_path = git.clone_or_fetch(input.repo_url, input.repo_dir_name, input.branch)
    latest_commit = git.get_latest_commit(repo_path, input.branch)
    return GitCloneFetchOutput(
        repo_path=str(repo_path),
        latest_commit=latest_commit,
    )


@activity.defn
async def chunk_files(input: ChunkFilesInput) -> ChunkFilesOutput:
    """Read files, chunk them, and write to the staging table."""
    settings = IngestionSettings()
    db = _make_db(settings)

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
            chunk_results = chunker.chunk_file(content, relative_path, language=language)

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
                        "language": chunk.language,
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


@activity.defn
async def get_changed_files(input: GetChangedFilesInput) -> list[str]:
    """Get the list of changed files between two commits."""
    settings = IngestionSettings()
    git = GitOperations(base_dir=settings.clone_base_dir)
    repo_path = Path(input.repo_path)
    changed = git.get_changed_files(repo_path, input.before_commit, input.after_commit)
    return [str(f.relative_to(repo_path)) for f in changed]


@activity.defn
async def delete_existing_chunks(input: DeleteChunksInput) -> int:
    """Delete all chunks for a repo+branch from postgres and Milvus."""
    settings = IngestionSettings()
    db = _make_db(settings)
    milvus = _make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        return svc.delete_by_branch(input.repository_id, input.branch)
    finally:
        db.close()
        milvus.close()


@activity.defn
async def delete_chunks_for_files(input: DeleteChunksForFilesInput) -> int:
    """Delete chunks for specific files from postgres and Milvus."""
    settings = IngestionSettings()
    db = _make_db(settings)
    milvus = _make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        return svc.delete_by_files(input.repository_id, input.branch, input.file_paths)
    finally:
        db.close()
        milvus.close()


@activity.defn
async def embed_chunk_batch(input: EmbedBatchInput) -> str:
    """Embed a batch of staging chunks and write vectors back."""
    settings = IngestionSettings()
    db = _make_db(settings)
    embedder = get_embedding_provider(
        EmbeddingStrategy(input.embedding_strategy),
        api_key=settings.openai_api_key,
    )
    try:
        svc = ChunkService(db)
        chunks = svc.read_staging_batch(input.batch_id, input.offset, input.limit)
        if not chunks:
            return "no_chunks"
        texts = [c.content for c in chunks]
        embeddings = embedder.embed_batch(texts)
        svc.write_staging_embeddings(input.batch_id, input.offset, embeddings)
        return f"embedded_{len(chunks)}"
    finally:
        db.close()


@activity.defn
async def store_chunks(input: StoreChunksInput) -> int:
    """Move staging chunks to final tables and Milvus."""
    settings = IngestionSettings()
    db = _make_db(settings)
    milvus = _make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        return svc.move_to_final(input.batch_id)
    finally:
        db.close()
        milvus.close()


@activity.defn
async def cleanup_staging(input: CleanupStagingInput) -> str:
    """Clean up staging rows on failure."""
    settings = IngestionSettings()
    db = _make_db(settings)
    try:
        svc = ChunkService(db)
        svc.cleanup_staging(input.batch_id)
        return "cleaned"
    finally:
        db.close()
