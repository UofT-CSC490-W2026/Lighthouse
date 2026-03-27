from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass

from db import Chunk, DatabaseManager, IndexedFile, StagingChunk
from vectordb import MilvusClient

logger = logging.getLogger(__name__)


@dataclass
class FilePublishCleanupTarget:
    file_path: str
    previous_publish_id: str | None


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

            milvus_batches: list[list[dict]] = []

            # Normalize and validate embeddings before mutating final storage.
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

                    raw_embedding = row.embedding
                    if isinstance(raw_embedding, memoryview):
                        raw_embedding = raw_embedding.tobytes()

                    embedding = json.loads(raw_embedding.decode("utf-8"))
                    milvus_records.append(
                        {
                            "id": row.id,
                            "chunk_id": row.id,
                            "embedding": embedding,
                            "repository_id": row.repository_id,
                            "file_path": row.file_path,
                            "branch": row.branch,
                            "publish_id": "legacy",
                        }
                    )
                milvus_batches.append(milvus_records)

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
                            "publish_id": "legacy",
                        }
                        for row in batch
                    ]
                ).on_conflict_ignore().execute()

            # Insert into Milvus
            for milvus_records in milvus_batches:
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

    def publish_incremental_batch(
        self,
        batch_id: str,
        repository_id: str,
        branch: str,
        changed_files: list[str],
    ) -> list[FilePublishCleanupTarget]:
        """Publish staged chunks for changed files without a delete-first gap."""
        milvus = self._ensure_milvus()

        with self.db.connection_context():
            staging_rows = list(
                StagingChunk.select()
                .where(StagingChunk.batch_id == batch_id)
                .order_by(StagingChunk.seq_index)
            )

            rows_by_file: dict[str, list[StagingChunk]] = {}
            for row in staging_rows:
                rows_by_file.setdefault(row.file_path, []).append(row)

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
                            "publish_id": batch_id,
                        }
                        for row in batch
                    ]
                ).on_conflict_ignore().execute()

            milvus_records: list[dict] = []
            for row in staging_rows:
                if row.embedding is None:
                    logger.warning(
                        "Staging chunk %s has no embedding, skipping Milvus insert",
                        row.id,
                    )
                    continue

                raw_embedding = row.embedding
                if isinstance(raw_embedding, memoryview):
                    raw_embedding = raw_embedding.tobytes()

                embedding = json.loads(raw_embedding.decode("utf-8"))
                milvus_records.append(
                    {
                        "id": row.id,
                        "chunk_id": row.id,
                        "embedding": embedding,
                        "repository_id": row.repository_id,
                        "file_path": row.file_path,
                        "branch": row.branch,
                        "publish_id": batch_id,
                    }
                )

            if milvus_records:
                for i in range(0, len(milvus_records), self.BATCH_SIZE):
                    milvus.insert(milvus_records[i : i + self.BATCH_SIZE])

            cleanup_targets: list[FilePublishCleanupTarget] = []
            with self.db.database.atomic():
                existing_rows = {
                    row.file_path: row
                    for row in IndexedFile.select().where(
                        (IndexedFile.repository == repository_id)
                        & (IndexedFile.branch_name == branch)
                        & (IndexedFile.file_path.in_(changed_files))
                    )
                }

                for file_path in changed_files:
                    previous_publish_id = None
                    if file_path in existing_rows:
                        previous_publish_id = existing_rows[file_path].active_publish_id

                    next_publish_id = batch_id if file_path in rows_by_file else None
                    cleanup_targets.append(
                        FilePublishCleanupTarget(
                            file_path=file_path,
                            previous_publish_id=previous_publish_id,
                        )
                    )

                    indexed_file, _ = IndexedFile.get_or_create(
                        repository=repository_id,
                        branch_name=branch,
                        file_path=file_path,
                        defaults={"active_publish_id": next_publish_id},
                    )
                    indexed_file.active_publish_id = next_publish_id
                    indexed_file.save()

                StagingChunk.delete().where(
                    StagingChunk.batch_id == batch_id
                ).execute()

        return [
            target
            for target in cleanup_targets
            if target.previous_publish_id not in {None, batch_id}
        ]

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

    def delete_by_publish_targets(
        self,
        repository_id: str,
        branch: str,
        cleanup_targets: list[FilePublishCleanupTarget],
    ) -> int:
        """Delete stale published chunks for specific files from postgres and Milvus."""
        milvus = self._ensure_milvus()
        total_deleted = 0

        with self.db.connection_context():
            for target in cleanup_targets:
                if target.previous_publish_id is None:
                    continue

                deleted = (
                    Chunk.delete()
                    .where(
                        (Chunk.repository == repository_id)
                        & (Chunk.branch == branch)
                        & (Chunk.file_path == target.file_path)
                        & (Chunk.publish_id == target.previous_publish_id)
                    )
                    .execute()
                )
                total_deleted += deleted

                milvus.delete_by_filter(
                    f'repository_id == "{repository_id}" and branch == "{branch}" '
                    f'and file_path == "{target.file_path}" '
                    f'and publish_id == "{target.previous_publish_id}"'
                )

        logger.info(
            "Deleted %d stale chunks across %d files",
            total_deleted,
            len(cleanup_targets),
        )
        return total_deleted
