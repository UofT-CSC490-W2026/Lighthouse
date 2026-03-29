from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from db import Chunk, DatabaseManager, IndexedFile, StagingChunk
from peewee import EXCLUDED
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

    @staticmethod
    def _decode_embedding(raw_embedding: bytes | memoryview) -> list[float]:
        if isinstance(raw_embedding, memoryview):
            raw_embedding = raw_embedding.tobytes()
        return json.loads(raw_embedding.decode("utf-8"))

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
                StagingChunk.select(
                    StagingChunk.id,
                    StagingChunk.repository_id,
                    StagingChunk.branch,
                    StagingChunk.file_path,
                    StagingChunk.start_line,
                    StagingChunk.end_line,
                    StagingChunk.content,
                    StagingChunk.language,
                    StagingChunk.chunk_hash,
                    StagingChunk.embedding,
                )
                .where(StagingChunk.batch_id == batch_id)
                .order_by(StagingChunk.seq_index)
                .tuples()
            )

            files_with_staged_chunks = {row[3] for row in staging_rows}

            for i in range(0, len(staging_rows), self.BATCH_SIZE):
                batch = staging_rows[i : i + self.BATCH_SIZE]
                Chunk.insert_many(
                    [
                        {
                            "id": row[0],
                            "repository": row[1],
                            "branch": row[2],
                            "file_path": row[3],
                            "start_line": row[4],
                            "end_line": row[5],
                            "content": row[6],
                            "language": row[7],
                            "chunk_hash": row[8],
                            "publish_id": batch_id,
                        }
                        for row in batch
                    ]
                ).on_conflict_ignore().execute()

            milvus_records: list[dict] = []
            for row in staging_rows:
                chunk_id = row[0]
                raw_embedding = row[9]
                if raw_embedding is None:
                    logger.warning(
                        "Staging chunk %s has no embedding, skipping Milvus insert",
                        chunk_id,
                    )
                    continue

                embedding = self._decode_embedding(raw_embedding)
                milvus_records.append(
                    {
                        "id": chunk_id,
                        "chunk_id": chunk_id,
                        "embedding": embedding,
                        "repository_id": row[1],
                        "file_path": row[3],
                        "branch": row[2],
                        "publish_id": batch_id,
                    }
                )

            if milvus_records:
                for i in range(0, len(milvus_records), self.BATCH_SIZE):
                    milvus.insert(milvus_records[i : i + self.BATCH_SIZE])

            cleanup_targets: list[FilePublishCleanupTarget] = []
            with self.db.database.atomic():
                existing_rows = {
                    row[0]: row[1]
                    for row in IndexedFile.select(
                        IndexedFile.file_path,
                        IndexedFile.active_publish_id,
                    ).where(
                        (IndexedFile.repository == repository_id)
                        & (IndexedFile.branch_name == branch)
                        & (IndexedFile.file_path.in_(changed_files))
                    ).tuples()
                }

                now = datetime.now(timezone.utc)
                indexed_updates = []
                for file_path in changed_files:
                    previous_publish_id = existing_rows.get(file_path)

                    next_publish_id = batch_id if file_path in files_with_staged_chunks else None
                    cleanup_targets.append(
                        FilePublishCleanupTarget(
                            file_path=file_path,
                            previous_publish_id=previous_publish_id,
                        )
                    )
                    indexed_updates.append(
                        {
                            "repository": repository_id,
                            "branch_name": branch,
                            "file_path": file_path,
                            "active_publish_id": next_publish_id,
                            "updated_at": now,
                        }
                    )

                for i in range(0, len(indexed_updates), self.BATCH_SIZE):
                    batch = indexed_updates[i : i + self.BATCH_SIZE]
                    IndexedFile.insert_many(batch).on_conflict(
                        conflict_target=[
                            IndexedFile.repository,
                            IndexedFile.branch_name,
                            IndexedFile.file_path,
                        ],
                        update={
                            IndexedFile.active_publish_id: EXCLUDED.active_publish_id,
                            IndexedFile.updated_at: EXCLUDED.updated_at,
                        },
                    ).execute()

                StagingChunk.delete().where(
                    StagingChunk.batch_id == batch_id
                ).execute()

        return [
            target
            for target in cleanup_targets
            if target.previous_publish_id not in {None, batch_id}
        ]

    def publish_full_batch(
        self,
        batch_id: str,
        repository_id: str,
        branch: str,
    ) -> list[FilePublishCleanupTarget]:
        """Publish all staged chunks for a full re-index without a delete-first gap.

        Unlike publish_incremental_batch, this method queries all existing
        indexed_files for the branch so that files deleted from the repo have
        their active_publish_id cleared and their old chunks are returned as
        cleanup targets.
        """
        milvus = self._ensure_milvus()

        with self.db.connection_context():
            staging_rows = list(
                StagingChunk.select(
                    StagingChunk.id,
                    StagingChunk.repository_id,
                    StagingChunk.branch,
                    StagingChunk.file_path,
                    StagingChunk.start_line,
                    StagingChunk.end_line,
                    StagingChunk.content,
                    StagingChunk.language,
                    StagingChunk.chunk_hash,
                    StagingChunk.embedding,
                )
                .where(StagingChunk.batch_id == batch_id)
                .order_by(StagingChunk.seq_index)
                .tuples()
            )

            files_with_staged_chunks = {row[3] for row in staging_rows}

            for i in range(0, len(staging_rows), self.BATCH_SIZE):
                batch = staging_rows[i : i + self.BATCH_SIZE]
                Chunk.insert_many(
                    [
                        {
                            "id": row[0],
                            "repository": row[1],
                            "branch": row[2],
                            "file_path": row[3],
                            "start_line": row[4],
                            "end_line": row[5],
                            "content": row[6],
                            "language": row[7],
                            "chunk_hash": row[8],
                            "publish_id": batch_id,
                        }
                        for row in batch
                    ]
                ).on_conflict_ignore().execute()

            milvus_records: list[dict] = []
            for row in staging_rows:
                chunk_id = row[0]
                raw_embedding = row[9]
                if raw_embedding is None:
                    logger.warning(
                        "Staging chunk %s has no embedding, skipping Milvus insert",
                        chunk_id,
                    )
                    continue

                embedding = self._decode_embedding(raw_embedding)
                milvus_records.append(
                    {
                        "id": chunk_id,
                        "chunk_id": chunk_id,
                        "embedding": embedding,
                        "repository_id": row[1],
                        "file_path": row[3],
                        "branch": row[2],
                        "publish_id": batch_id,
                    }
                )

            if milvus_records:
                for i in range(0, len(milvus_records), self.BATCH_SIZE):
                    milvus.insert(milvus_records[i : i + self.BATCH_SIZE])

            cleanup_targets: list[FilePublishCleanupTarget] = []
            with self.db.database.atomic():
                # Query ALL currently indexed files for this branch, not just
                # a caller-supplied subset, so deleted files are also handled.
                existing_rows = {
                    row[0]: row[1]
                    for row in IndexedFile.select(
                        IndexedFile.file_path,
                        IndexedFile.active_publish_id,
                    ).where(
                        (IndexedFile.repository == repository_id)
                        & (IndexedFile.branch_name == branch)
                    ).tuples()
                }

                all_files = set(existing_rows.keys()) | files_with_staged_chunks

                now = datetime.now(timezone.utc)
                indexed_updates = []
                for file_path in all_files:
                    previous_publish_id = existing_rows.get(file_path)
                    next_publish_id = batch_id if file_path in files_with_staged_chunks else None
                    cleanup_targets.append(
                        FilePublishCleanupTarget(
                            file_path=file_path,
                            previous_publish_id=previous_publish_id,
                        )
                    )
                    indexed_updates.append(
                        {
                            "repository": repository_id,
                            "branch_name": branch,
                            "file_path": file_path,
                            "active_publish_id": next_publish_id,
                            "updated_at": now,
                        }
                    )

                for i in range(0, len(indexed_updates), self.BATCH_SIZE):
                    batch = indexed_updates[i : i + self.BATCH_SIZE]
                    IndexedFile.insert_many(batch).on_conflict(
                        conflict_target=[
                            IndexedFile.repository,
                            IndexedFile.branch_name,
                            IndexedFile.file_path,
                        ],
                        update={
                            IndexedFile.active_publish_id: EXCLUDED.active_publish_id,
                            IndexedFile.updated_at: EXCLUDED.updated_at,
                        },
                    ).execute()

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
