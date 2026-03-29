from __future__ import annotations

import json
import logging
import uuid

from db import DatabaseManager, StagingWikiPage, WikiGeneration, WikiPage
from vectordb import MilvusClient

logger = logging.getLogger(__name__)


class WikiService:
    """Operations on staging and final wiki page tables + Milvus."""

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

    # --- WikiGeneration operations ---

    def create_generation(
        self,
        repository_id: str,
        branch: str,
        wiki_title: str,
        wiki_description: str,
        structure_json: str,
        page_count: int,
    ) -> WikiGeneration:
        """Create a WikiGeneration record."""
        with self.db.connection_context():
            return WikiGeneration.create(
                repository_id=repository_id,
                branch=branch,
                status="generating",
                wiki_title=wiki_title,
                wiki_description=wiki_description,
                structure_json=structure_json,
                page_count=page_count,
            )

    def update_status(self, wiki_generation_id: str, status: str, page_count: int = 0) -> None:
        """Update the status of a WikiGeneration record."""
        with self.db.connection_context():
            updates: dict = {"status": status}
            if page_count > 0:
                updates["page_count"] = page_count
            WikiGeneration.update(**updates).where(
                WikiGeneration.id == wiki_generation_id
            ).execute()

    # --- Staging operations ---

    def write_staging(self, batch_id: str, pages: list[dict]) -> int:
        """Write wiki page records to the staging table. Returns count written."""
        with self.db.connection_context():
            for i in range(0, len(pages), self.BATCH_SIZE):
                batch = pages[i : i + self.BATCH_SIZE]
                StagingWikiPage.insert_many(
                    [
                        {
                            "id": p.get("id", str(uuid.uuid4())),
                            "batch_id": batch_id,
                            "seq_index": i + j,
                            "repository_id": p["repository_id"],
                            "branch": p["branch"],
                            "slug": p["slug"],
                            "title": p["title"],
                            "content": p.get("content", ""),
                            "section_path": p["section_path"],
                            "related_pages": p.get("related_pages"),
                            "source_files": p.get("source_files"),
                        }
                        for j, p in enumerate(batch)
                    ]
                ).execute()
        return len(pages)

    def read_staging_batch(
        self, batch_id: str, offset: int, limit: int
    ) -> list[StagingWikiPage]:
        """Read a batch of staging wiki pages ordered by seq_index."""
        with self.db.connection_context():
            return list(
                StagingWikiPage.select()
                .where(
                    (StagingWikiPage.batch_id == batch_id)
                    & (StagingWikiPage.seq_index >= offset)
                    & (StagingWikiPage.seq_index < offset + limit)
                )
                .order_by(StagingWikiPage.seq_index)
            )

    def update_staging_content_by_slug(self, batch_id: str, slug: str, content: str) -> None:
        """Update the content of a staging wiki page after LLM generation."""
        with self.db.connection_context():
            StagingWikiPage.update(content=content).where(
                (StagingWikiPage.batch_id == batch_id)
                & (StagingWikiPage.slug == slug)
            ).execute()

    def write_staging_embeddings(
        self, batch_id: str, offset: int, embeddings: list[list[float]]
    ) -> None:
        """Write embedding vectors back to staging rows."""
        with self.db.connection_context():
            rows = list(
                StagingWikiPage.select(StagingWikiPage.id, StagingWikiPage.seq_index)
                .where(
                    (StagingWikiPage.batch_id == batch_id)
                    & (StagingWikiPage.seq_index >= offset)
                    & (StagingWikiPage.seq_index < offset + len(embeddings))
                )
                .order_by(StagingWikiPage.seq_index)
            )
            for row, emb in zip(rows, embeddings):
                StagingWikiPage.update(
                    embedding=json.dumps(emb).encode("utf-8")
                ).where(StagingWikiPage.id == row.id).execute()

    def move_to_final(self, batch_id: str, wiki_generation_id: str) -> int:
        """Move staging wiki pages to final table + Milvus, then clean up staging."""
        milvus = self._ensure_milvus()
        count = 0

        with self.db.connection_context():
            staging_rows = list(
                StagingWikiPage.select()
                .where(StagingWikiPage.batch_id == batch_id)
                .order_by(StagingWikiPage.seq_index)
            )

            if not staging_rows:
                return 0

            milvus_batches: list[list[dict]] = []

            for i in range(0, len(staging_rows), self.BATCH_SIZE):
                batch = staging_rows[i : i + self.BATCH_SIZE]
                milvus_records = []
                for row in batch:
                    if row.embedding is None:
                        logger.warning(
                            "Staging wiki page %s has no embedding, skipping Milvus insert",
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
                            "file_path": row.slug,
                            "branch": row.branch,
                            "publish_id": "legacy",
                        }
                    )
                milvus_batches.append(milvus_records)

            # Insert into postgres wiki_pages table
            for i in range(0, len(staging_rows), self.BATCH_SIZE):
                batch = staging_rows[i : i + self.BATCH_SIZE]
                WikiPage.insert_many(
                    [
                        {
                            "id": row.id,
                            "wiki_generation": wiki_generation_id,
                            "repository": row.repository_id,
                            "branch": row.branch,
                            "slug": row.slug,
                            "title": row.title,
                            "content": row.content,
                            "section_path": row.section_path,
                            "related_pages": row.related_pages,
                            "source_files": row.source_files,
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
            StagingWikiPage.delete().where(
                StagingWikiPage.batch_id == batch_id
            ).execute()

        logger.info(
            "Moved %d wiki pages from staging to final for batch %s", count, batch_id
        )
        return count

    def cleanup_staging(self, batch_id: str) -> None:
        """Delete staging rows for a batch (e.g., on failure)."""
        with self.db.connection_context():
            deleted = (
                StagingWikiPage.delete()
                .where(StagingWikiPage.batch_id == batch_id)
                .execute()
            )
            logger.info("Cleaned up %d staging wiki rows for batch %s", deleted, batch_id)
