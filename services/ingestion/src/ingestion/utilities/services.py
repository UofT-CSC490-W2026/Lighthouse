from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from db import Chunk, DatabaseManager, IndexedBranch, Repository, StagingChunk
from shared.config import EMBEDDING_DIMENSION, MILVUS_COLLECTION_NAME
from vectordb import MilvusClient

logger = logging.getLogger(__name__)


class RepositoryService:
    """CRUD operations for Repository records."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    def ensure(
        self, github_repo_id: int, repo_url: str, full_name: str
    ) -> str:
        """Get or create a Repository record, returning its id."""
        with self.db.connection_context():
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
            return repo.id


class BranchService:
    """Manage IndexedBranch status and metadata."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    def update_status(
        self,
        repository_id: str,
        branch: str,
        status: str,
        latest_commit: str | None = None,
        github_token: str | None = None,
    ) -> str:
        """Update or create an IndexedBranch record with the given status."""
        with self.db.connection_context():
            indexed_branch, _ = IndexedBranch.get_or_create(
                repository_id=repository_id,
                branch_name=branch,
                defaults={
                    "status": "pending",
                    "github_token_encrypted": github_token,
                },
            )
            indexed_branch.status = status
            indexed_branch.updated_at = datetime.now(timezone.utc)
            if latest_commit is not None:
                indexed_branch.last_indexed_commit = latest_commit
            if status == "indexed":
                indexed_branch.indexed_at = datetime.now(timezone.utc)
            if github_token is not None:
                indexed_branch.github_token_encrypted = github_token
            indexed_branch.save()
            return status

    def get_github_token(self, repository_id: str, branch: str) -> str | None:
        """Retrieve the stored github token for a branch."""
        with self.db.connection_context():
            ib = IndexedBranch.get_or_none(
                (IndexedBranch.repository_id == repository_id)
                & (IndexedBranch.branch_name == branch)
            )
            if ib is None:
                return None
            return ib.github_token_encrypted


class ChunkService:
    """Operations on staging and final chunk tables + Milvus."""

    BATCH_SIZE = 500

    def __init__(
        self,
        db_manager: DatabaseManager,
        milvus: MilvusClient | None = None,
    ) -> None:
        self.db = db_manager
        self.milvus = milvus

    def _ensure_milvus(self) -> MilvusClient:
        if self.milvus is None:
            raise RuntimeError("MilvusClient not provided")
        return self.milvus

    # --- Staging operations ---

    def write_staging(
        self, batch_id: str, chunks: list[dict]
    ) -> int:
        """Write chunk records to the staging table. Returns count written."""
        with self.db.connection_context():
            for i in range(0, len(chunks), self.BATCH_SIZE):
                batch = chunks[i : i + self.BATCH_SIZE]
                StagingChunk.insert_many(
                    [
                        {
                            "id": c.get("chunk_id", str(uuid.uuid4())),
                            "batch_id": batch_id,
                            "seq_index": i + j,
                            "repository_id": c["repository_id"],
                            "branch": c["branch"],
                            "file_path": c["file_path"],
                            "start_line": c["start_line"],
                            "end_line": c["end_line"],
                            "content": c["content"],
                            "language": c.get("language"),
                            "chunk_hash": c["chunk_hash"],
                        }
                        for j, c in enumerate(batch)
                    ]
                ).execute()
        return len(chunks)

    def read_staging_batch(
        self, batch_id: str, offset: int, limit: int
    ) -> list[StagingChunk]:
        """Read a batch of staging chunks ordered by seq_index."""
        with self.db.connection_context():
            return list(
                StagingChunk.select()
                .where(
                    (StagingChunk.batch_id == batch_id)
                    & (StagingChunk.seq_index >= offset)
                    & (StagingChunk.seq_index < offset + limit)
                )
                .order_by(StagingChunk.seq_index)
            )

    def write_staging_embeddings(
        self, batch_id: str, offset: int, embeddings: list[list[float]]
    ) -> None:
        """Write embedding vectors back to staging rows."""
        with self.db.connection_context():
            rows = list(
                StagingChunk.select(StagingChunk.id, StagingChunk.seq_index)
                .where(
                    (StagingChunk.batch_id == batch_id)
                    & (StagingChunk.seq_index >= offset)
                    & (StagingChunk.seq_index < offset + len(embeddings))
                )
                .order_by(StagingChunk.seq_index)
            )
            for row, emb in zip(rows, embeddings):
                StagingChunk.update(
                    embedding=json.dumps(emb).encode("utf-8")
                ).where(StagingChunk.id == row.id).execute()

    def move_to_final(self, batch_id: str) -> int:
        """Move staging chunks to final chunks table + Milvus, then clean up staging."""
        milvus = self._ensure_milvus()
        count = 0

        with self.db.connection_context():
            staging_rows = list(
                StagingChunk.select()
                .where(StagingChunk.batch_id == batch_id)
                .order_by(StagingChunk.seq_index)
            )

            if not staging_rows:
                return 0

            # Insert into postgres chunks table
            for i in range(0, len(staging_rows), self.BATCH_SIZE):
                batch = staging_rows[i : i + self.BATCH_SIZE]
                Chunk.insert_many(
                    [
                        {
                            "id": row.id,
                            "repository": row.repository_id,
                            "branch": row.branch,
                            "file_path": row.file_path,
                            "start_line": row.start_line,
                            "end_line": row.end_line,
                            "content": row.content,
                            "language": row.language,
                            "chunk_hash": row.chunk_hash,
                        }
                        for row in batch
                    ]
                ).execute()

            # Insert into Milvus
            for i in range(0, len(staging_rows), self.BATCH_SIZE):
                batch = staging_rows[i : i + self.BATCH_SIZE]
                milvus_records = []
                for row in batch:
                    if row.embedding is None:
                        logger.warning(
                            "Staging chunk %s has no embedding, skipping Milvus insert",
                            row.id,
                        )
                        continue
                    embedding = json.loads(row.embedding.decode("utf-8"))
                    milvus_records.append(
                        {
                            "id": row.id,
                            "chunk_id": row.id,
                            "embedding": embedding,
                            "repository_id": row.repository_id,
                            "file_path": row.file_path,
                            "branch": row.branch,
                        }
                    )
                if milvus_records:
                    milvus.insert(milvus_records)

            count = len(staging_rows)

            # Clean up staging
            StagingChunk.delete().where(
                StagingChunk.batch_id == batch_id
            ).execute()

        logger.info(
            "Moved %d chunks from staging to final for batch %s", count, batch_id
        )
        return count

    def cleanup_staging(self, batch_id: str) -> None:
        """Delete staging rows for a batch (e.g., on failure)."""
        with self.db.connection_context():
            deleted = (
                StagingChunk.delete()
                .where(StagingChunk.batch_id == batch_id)
                .execute()
            )
            logger.info("Cleaned up %d staging rows for batch %s", deleted, batch_id)

    # --- Final table operations ---

    def delete_by_branch(self, repository_id: str, branch: str) -> int:
        """Delete all chunks for a repo+branch from postgres and Milvus."""
        milvus = self._ensure_milvus()

        with self.db.connection_context():
            deleted = (
                Chunk.delete()
                .where(
                    (Chunk.repository == repository_id) & (Chunk.branch == branch)
                )
                .execute()
            )
            logger.info("Deleted %d chunks from postgres", deleted)

        milvus.delete_by_filter(
            f'repository_id == "{repository_id}" and branch == "{branch}"'
        )
        return deleted

    def delete_by_files(
        self, repository_id: str, branch: str, file_paths: list[str]
    ) -> int:
        """Delete chunks for specific files from postgres and Milvus."""
        milvus = self._ensure_milvus()
        total_deleted = 0

        with self.db.connection_context():
            for rel_path in file_paths:
                deleted = (
                    Chunk.delete()
                    .where(
                        (Chunk.repository == repository_id)
                        & (Chunk.branch == branch)
                        & (Chunk.file_path == rel_path)
                    )
                    .execute()
                )
                total_deleted += deleted

                milvus.delete_by_filter(
                    f'repository_id == "{repository_id}" and branch == "{branch}" '
                    f'and file_path == "{rel_path}"'
                )

        logger.info("Deleted %d chunks for %d files", total_deleted, len(file_paths))
        return total_deleted
