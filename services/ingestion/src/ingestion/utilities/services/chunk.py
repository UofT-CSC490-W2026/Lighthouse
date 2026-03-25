from __future__ import annotations

import json
import logging
import uuid

from db import Chunk, DatabaseManager, StagingChunk
from vectordb import MilvusClient

logger = logging.getLogger(__name__)


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
