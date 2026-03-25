from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from db import CodeChunk, DatabaseManager, IndexedBranch, Repository
from shared.config import EMBEDDING_DIMENSION, MILVUS_COLLECTION_NAME
from vectordb import MilvusClient

from embedding import OpenAIEmbeddingProvider

from ..chunking import SlidingWindowChunker

from .config import IngestionSettings
from .git_ops import GitOperations

logger = logging.getLogger(__name__)


class IndexingPipeline:
    """Orchestrates the full indexing pipeline: git -> chunk -> embed -> store."""

    def __init__(self, settings: IngestionSettings) -> None:
        self.settings = settings
        self.db_manager = DatabaseManager(settings.postgres_dsn)
        self.milvus = MilvusClient(
            uri=settings.milvus_uri,
            collection_name=MILVUS_COLLECTION_NAME,
        )
        self.embedder = OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
        )
        self.chunker = SlidingWindowChunker()

    def initialize(self) -> None:
        """Connect to databases and ensure collections exist."""
        self.db_manager.connect()
        self.milvus.ensure_collection(dimension=EMBEDDING_DIMENSION)

    def close(self) -> None:
        """Clean up connections."""
        self.db_manager.close()
        self.milvus.close()

    def index_repository(
        self,
        github_repo_id: int,
        repo_url: str,
        full_name: str,
        branches: list[str],
        github_token: str | None = None,
    ) -> None:
        """Full indexing pipeline for a repository."""
        with self.db_manager.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == github_repo_id
            )
            if repo is None:
                parts = full_name.split("/")
                owner = parts[0] if len(parts) > 1 else ""
                name = parts[-1]
                repo = Repository.create(
                    github_repo_id=github_repo_id,
                    full_name=full_name,
                    repo_url=repo_url,
                    display_name=name,
                    owner_login=owner,
                    owner_type="User",
                )
                logger.info("Created repository record: %s", full_name)
            else:
                # Update mutable fields in case of a rename
                if repo.full_name != full_name:
                    logger.info(
                        "Repository renamed: %s -> %s", repo.full_name, full_name
                    )
                    repo.full_name = full_name
                    parts = full_name.split("/")
                    repo.owner_login = parts[0] if len(parts) > 1 else ""
                    repo.display_name = parts[-1]
                if repo.repo_url != repo_url:
                    repo.repo_url = repo_url
                repo.save()

            for branch in branches:
                self._index_branch(repo, branch, repo_url, github_token)

    def _index_branch(
        self,
        repo: Repository,
        branch: str,
        repo_url: str,
        github_token: str | None,
    ) -> None:
        """Index a single branch of a repository."""
        indexed_branch, _ = IndexedBranch.get_or_create(
            repository=repo,
            branch_name=branch,
            defaults={"status": "pending", "github_token_encrypted": github_token},
        )

        # Update status to indexing
        indexed_branch.status = "indexing"
        indexed_branch.updated_at = datetime.now(timezone.utc)
        if github_token:
            indexed_branch.github_token_encrypted = github_token
        indexed_branch.save()

        try:
            git = GitOperations(
                base_dir=self.settings.clone_base_dir,
                github_token=github_token,
            )
            repo_path = git.clone_or_fetch(
                repo_url, str(repo.github_repo_id), branch
            )
            latest_commit = git.get_latest_commit(repo_path, branch)

            # Get all code files
            files = git.list_files(repo_path)
            logger.info(
                "Found %d files to index for %s/%s",
                len(files),
                repo.full_name,
                branch,
            )

            # Delete existing chunks for this repo+branch
            self._delete_existing_chunks(repo.id, branch)

            # Chunk and embed all files
            self._process_files(repo, branch, repo_path, files)

            # Update indexed branch status
            indexed_branch.status = "indexed"
            indexed_branch.last_indexed_commit = latest_commit
            indexed_branch.indexed_at = datetime.now(timezone.utc)
            indexed_branch.updated_at = datetime.now(timezone.utc)
            indexed_branch.save()

            logger.info(
                "Successfully indexed %s/%s at %s",
                repo.full_name,
                branch,
                latest_commit,
            )

        except Exception:
            indexed_branch.status = "failed"
            indexed_branch.updated_at = datetime.now(timezone.utc)
            indexed_branch.save()
            logger.exception("Failed to index %s/%s", repo.full_name, branch)
            raise

    def _delete_existing_chunks(self, repository_id: str, branch: str) -> None:
        """Delete existing chunks from postgres and milvus for a repo+branch."""
        # Delete from postgres
        deleted = (
            CodeChunk.delete()
            .where(
                (CodeChunk.repository == repository_id) & (CodeChunk.branch == branch)
            )
            .execute()
        )
        logger.info("Deleted %d existing chunks from postgres", deleted)

        # Delete from milvus
        self.milvus.delete_by_filter(
            f'repository_id == "{repository_id}" and branch == "{branch}"'
        )

    def _process_files(
        self,
        repo: Repository,
        branch: str,
        repo_path: Path,
        files: list[Path],
    ) -> None:
        """Chunk, embed, and store all files."""
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
            chunk_results = self.chunker.chunk_file(content, relative_path)

            for chunk in chunk_results:
                chunk_id = str(uuid.uuid4())
                all_chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "repository_id": repo.id,
                        "branch": branch,
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
            return

        logger.info("Processing %d chunks", len(all_chunks))

        # Embed all chunks in batches
        texts = [c["content"] for c in all_chunks]
        embeddings = self.embedder.embed_batch(texts)

        # Insert into postgres (batch)
        batch_size = 500
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i : i + batch_size]
            CodeChunk.insert_many(
                [
                    {
                        "id": c["chunk_id"],
                        "repository": c["repository_id"],
                        "branch": c["branch"],
                        "file_path": c["file_path"],
                        "start_line": c["start_line"],
                        "end_line": c["end_line"],
                        "content": c["content"],
                        "language": c["language"],
                        "chunk_hash": c["chunk_hash"],
                    }
                    for c in batch
                ]
            ).execute()

        # Insert into milvus (batch)
        milvus_records = [
            {
                "id": c["chunk_id"],
                "chunk_id": c["chunk_id"],
                "embedding": embeddings[i],
                "repository_id": c["repository_id"],
                "file_path": c["file_path"],
                "branch": c["branch"],
            }
            for i, c in enumerate(all_chunks)
        ]
        for i in range(0, len(milvus_records), batch_size):
            self.milvus.insert(milvus_records[i : i + batch_size])

        logger.info("Stored %d chunks in postgres and milvus", len(all_chunks))

    def incremental_index(
        self,
        github_repo_id: int,
        full_name: str,
        branch: str,
        before_commit: str,
        after_commit: str,
    ) -> None:
        """Incremental indexing for push events - only re-index changed files."""
        with self.db_manager.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == github_repo_id
            )
            if repo is None:
                logger.warning(
                    "Repository %s not found, skipping incremental index",
                    full_name,
                )
                return

            # Update mutable fields in case of a rename
            if repo.full_name != full_name:
                logger.info(
                    "Repository renamed: %s -> %s", repo.full_name, full_name
                )
                repo.full_name = full_name
                parts = full_name.split("/")
                repo.owner_login = parts[0] if len(parts) > 1 else ""
                repo.display_name = parts[-1]
                repo.save()

            indexed_branch = IndexedBranch.get_or_none(
                (IndexedBranch.repository == repo)
                & (IndexedBranch.branch_name == branch)
            )
            if indexed_branch is None:
                logger.warning(
                    "Branch %s/%s not indexed, skipping incremental index",
                    full_name,
                    branch,
                )
                return

            github_token = indexed_branch.github_token_encrypted

            indexed_branch.status = "indexing"
            indexed_branch.updated_at = datetime.now(timezone.utc)
            indexed_branch.save()

            try:
                git = GitOperations(
                    base_dir=self.settings.clone_base_dir,
                    github_token=github_token,
                )
                repo_path = git.clone_or_fetch(
                    repo.repo_url, str(repo.github_repo_id), branch
                )
                changed_files = git.get_changed_files(
                    repo_path, before_commit, after_commit
                )

                if not changed_files:
                    logger.info(
                        "No files changed between %s and %s",
                        before_commit,
                        after_commit,
                    )
                    indexed_branch.status = "indexed"
                    indexed_branch.last_indexed_commit = after_commit
                    indexed_branch.updated_at = datetime.now(timezone.utc)
                    indexed_branch.save()
                    return

                logger.info(
                    "Re-indexing %d changed files for %s/%s",
                    len(changed_files),
                    full_name,
                    branch,
                )

                # Delete chunks for changed files
                relative_paths = [
                    str(f.relative_to(repo_path)) for f in changed_files
                ]
                for rel_path in relative_paths:
                    # Delete from postgres
                    CodeChunk.delete().where(
                        (CodeChunk.repository == repo.id)
                        & (CodeChunk.branch == branch)
                        & (CodeChunk.file_path == rel_path)
                    ).execute()
                    # Delete from milvus
                    self.milvus.delete_by_filter(
                        f'repository_id == "{repo.id}" and branch == "{branch}" '
                        f'and file_path == "{rel_path}"'
                    )

                # Re-process changed files
                existing_files = [f for f in changed_files if f.exists()]
                self._process_files(repo, branch, repo_path, existing_files)

                indexed_branch.status = "indexed"
                indexed_branch.last_indexed_commit = after_commit
                indexed_branch.indexed_at = datetime.now(timezone.utc)
                indexed_branch.updated_at = datetime.now(timezone.utc)
                indexed_branch.save()

            except Exception:
                indexed_branch.status = "failed"
                indexed_branch.updated_at = datetime.now(timezone.utc)
                indexed_branch.save()
                logger.exception(
                    "Failed incremental index for %s/%s", full_name, branch
                )
                raise
