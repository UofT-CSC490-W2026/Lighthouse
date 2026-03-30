import json
import uuid

import pytest
from db import StagingWikiPage, WikiGeneration, WikiPage
from ingestion.utilities.services.wiki import WikiService
from testing_utils.factories import create_repository
from testing_utils.mock_embedding import MockEmbeddingProvider


@pytest.mark.integration
class TestWikiServiceGeneration:
    def test_create_generation(self, db_manager):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager)
        gen = svc.create_generation(
            repository_id=repo.id,
            branch="main",
            wiki_title="Test Wiki",
            wiki_description="A test wiki.",
            structure_json='{"sections": []}',
            page_count=3,
        )
        assert gen.status == "generating"
        assert gen.wiki_title == "Test Wiki"
        assert gen.page_count == 3

    def test_update_status(self, db_manager):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager)
        gen = svc.create_generation(
            repository_id=repo.id,
            branch="main",
            wiki_title="Test",
            wiki_description="",
            structure_json="{}",
            page_count=0,
        )
        svc.update_status(gen.id, "completed", page_count=5)
        with db_manager.connection_context():
            updated = WikiGeneration.get_by_id(gen.id)
            assert updated.status == "completed"
            assert updated.page_count == 5


@pytest.mark.integration
class TestWikiServiceStaging:
    def _make_pages(self, repo_id, count=3):
        return [
            {
                "repository_id": repo_id,
                "branch": "main",
                "slug": f"page-{i}",
                "title": f"Page {i}",
                "content": "",
                "section_path": "overview",
            }
            for i in range(count)
        ]

    def test_write_staging(self, db_manager):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager)
        batch_id = str(uuid.uuid4())
        count = svc.write_staging(batch_id, self._make_pages(repo.id, 3))
        assert count == 3
        with db_manager.connection_context():
            assert (
                StagingWikiPage.select()
                .where(StagingWikiPage.batch_id == batch_id)
                .count()
                == 3
            )

    def test_read_staging_batch(self, db_manager):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager)
        batch_id = str(uuid.uuid4())
        svc.write_staging(batch_id, self._make_pages(repo.id, 10))
        results = svc.read_staging_batch(batch_id, offset=2, limit=3)
        assert len(results) == 3
        assert results[0].seq_index == 2

    def test_update_staging_content_by_slug(self, db_manager):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager)
        batch_id = str(uuid.uuid4())
        svc.write_staging(batch_id, self._make_pages(repo.id, 1))
        svc.update_staging_content_by_slug(batch_id, "page-0", "# Generated Content")
        with db_manager.connection_context():
            row = StagingWikiPage.get(
                (StagingWikiPage.batch_id == batch_id)
                & (StagingWikiPage.slug == "page-0")
            )
            assert row.content == "# Generated Content"

    def test_write_staging_embeddings(self, db_manager):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager)
        batch_id = str(uuid.uuid4())
        svc.write_staging(batch_id, self._make_pages(repo.id, 3))
        embeddings = [[0.1, 0.2, 0.3] for _ in range(3)]
        svc.write_staging_embeddings(batch_id, 0, embeddings)
        with db_manager.connection_context():
            rows = list(
                StagingWikiPage.select()
                .where(StagingWikiPage.batch_id == batch_id)
                .order_by(StagingWikiPage.seq_index)
            )
            for row in rows:
                raw = row.embedding
                if isinstance(raw, memoryview):
                    raw = raw.tobytes()
                assert json.loads(raw) == [0.1, 0.2, 0.3]

    def test_cleanup_staging(self, db_manager):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager)
        batch_id = str(uuid.uuid4())
        svc.write_staging(batch_id, self._make_pages(repo.id, 5))
        svc.cleanup_staging(batch_id)
        with db_manager.connection_context():
            assert (
                StagingWikiPage.select()
                .where(StagingWikiPage.batch_id == batch_id)
                .count()
                == 0
            )


@pytest.mark.integration
class TestWikiServiceFinal:
    def _stage_with_embeddings(self, db_manager, milvus_client, repo_id, count=3, dim=8):
        svc = WikiService(db_manager, milvus_client)
        batch_id = str(uuid.uuid4())
        embedder = MockEmbeddingProvider(dimension=dim)
        pages = []
        for i in range(count):
            pages.append(
                {
                    "repository_id": repo_id,
                    "branch": "main",
                    "slug": f"page-{uuid.uuid4().hex[:8]}",
                    "title": f"Page {i}",
                    "content": f"# Page {i}\n\nContent for page {i}.",
                    "section_path": "overview",
                }
            )
        svc.write_staging(batch_id, pages)

        # Update content (simulating generate_wiki_page)
        with db_manager.connection_context():
            staging_rows = list(
                StagingWikiPage.select()
                .where(StagingWikiPage.batch_id == batch_id)
                .order_by(StagingWikiPage.seq_index)
            )
        texts = [r.content for r in staging_rows]
        embeddings = embedder.embed_batch(texts)
        svc.write_staging_embeddings(batch_id, 0, embeddings)
        return svc, batch_id

    def test_ensure_milvus_raises_when_not_provided(self, db_manager):
        svc = WikiService(db_manager)
        with pytest.raises(RuntimeError, match="MilvusClient not provided"):
            svc._ensure_milvus()

    def test_move_to_final_empty_staging_returns_zero(self, db_manager, milvus_client):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager, milvus_client)
        gen = svc.create_generation(
            repository_id=repo.id,
            branch="main",
            wiki_title="Empty",
            wiki_description="",
            structure_json="{}",
            page_count=0,
        )
        count = svc.move_to_final("nonexistent-batch-id", gen.id)
        assert count == 0

    def test_move_to_final_skips_pages_with_no_embedding(self, db_manager, milvus_client):
        repo = create_repository(db_manager)
        svc = WikiService(db_manager, milvus_client)
        batch_id = str(uuid.uuid4())
        # Write staging pages WITHOUT embeddings
        pages = [
            {
                "repository_id": repo.id,
                "branch": "main",
                "slug": f"page-{i}",
                "title": f"Page {i}",
                "content": f"content {i}",
                "section_path": "overview",
            }
            for i in range(2)
        ]
        svc.write_staging(batch_id, pages)
        gen = svc.create_generation(
            repository_id=repo.id,
            branch="main",
            wiki_title="Test",
            wiki_description="",
            structure_json="{}",
            page_count=2,
        )
        # Pages have no embedding — move_to_final should skip Milvus insert for them
        count = svc.move_to_final(batch_id, gen.id)
        assert count == 2  # Postgres insert still happens; Milvus is skipped

    def test_move_to_final(self, db_manager, milvus_client):
        repo = create_repository(db_manager)
        svc, batch_id = self._stage_with_embeddings(db_manager, milvus_client, repo.id)

        # Create a generation record
        gen = svc.create_generation(
            repository_id=repo.id,
            branch="main",
            wiki_title="Test",
            wiki_description="",
            structure_json="{}",
            page_count=3,
        )

        count = svc.move_to_final(batch_id, gen.id)
        assert count == 3
        with db_manager.connection_context():
            assert WikiPage.select().where(WikiPage.repository == repo.id).count() == 3
            assert (
                StagingWikiPage.select()
                .where(StagingWikiPage.batch_id == batch_id)
                .count()
                == 0
            )
