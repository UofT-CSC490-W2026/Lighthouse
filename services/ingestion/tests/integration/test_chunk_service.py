import json
import uuid

import pytest
from db import Chunk, IndexedFile, StagingChunk
from ingestion.utilities.services.chunk import ChunkService, FilePublishCleanupTarget
from testing_utils.factories import create_repository
from testing_utils.mock_embedding import MockEmbeddingProvider

@pytest.mark.integration
class TestChunkServiceStaging:
    def _make_chunks(self, repo_id, count=3):
        return [
            {
                "chunk_id": str(uuid.uuid4()),
                "repository_id": repo_id,
                "branch": "main",
                "file_path": f"file{i}.py",
                "start_line": i * 10 + 1,
                "end_line": (i + 1) * 10,
                "content": f"content {i}",
                "language": "python",
                "chunk_hash": f"hash{i}",
            }
            for i in range(count)
        ]

    def test_write_staging(self, db_manager):
        repo = create_repository(db_manager)
        svc = ChunkService(db_manager)
        batch_id = str(uuid.uuid4())
        chunks = self._make_chunks(repo.id, 3)
        count = svc.write_staging(batch_id, chunks)
        assert count == 3
        with db_manager.connection_context():
            assert StagingChunk.select().where(StagingChunk.batch_id == batch_id).count() == 3

    def test_write_staging_batching(self, db_manager):
        """Test that >500 chunks are written in batches."""
        repo = create_repository(db_manager)
        svc = ChunkService(db_manager)
        batch_id = str(uuid.uuid4())
        chunks = self._make_chunks(repo.id, 600)
        count = svc.write_staging(batch_id, chunks)
        assert count == 600
        with db_manager.connection_context():
            assert StagingChunk.select().where(StagingChunk.batch_id == batch_id).count() == 600

    def test_read_staging_batch(self, db_manager):
        repo = create_repository(db_manager)
        svc = ChunkService(db_manager)
        batch_id = str(uuid.uuid4())
        chunks = self._make_chunks(repo.id, 10)
        svc.write_staging(batch_id, chunks)
        results = svc.read_staging_batch(batch_id, offset=2, limit=3)
        assert len(results) == 3
        assert results[0].seq_index == 2

    def test_write_staging_embeddings(self, db_manager):
        repo = create_repository(db_manager)
        svc = ChunkService(db_manager)
        batch_id = str(uuid.uuid4())
        chunks = self._make_chunks(repo.id, 3)
        svc.write_staging(batch_id, chunks)
        embeddings = [[0.1, 0.2, 0.3] for _ in range(3)]
        svc.write_staging_embeddings(batch_id, 0, embeddings)
        with db_manager.connection_context():
            rows = list(StagingChunk.select().where(StagingChunk.batch_id == batch_id).order_by(StagingChunk.seq_index))
            for row in rows:
                raw = row.embedding
                if isinstance(raw, memoryview):
                    raw = raw.tobytes()
                assert json.loads(raw) == [0.1, 0.2, 0.3]

    def test_cleanup_staging(self, db_manager):
        repo = create_repository(db_manager)
        svc = ChunkService(db_manager)
        batch_id = str(uuid.uuid4())
        svc.write_staging(batch_id, self._make_chunks(repo.id, 5))
        svc.cleanup_staging(batch_id)
        with db_manager.connection_context():
            assert StagingChunk.select().where(StagingChunk.batch_id == batch_id).count() == 0


@pytest.mark.integration
class TestChunkServiceFinal:
    def _stage_with_embeddings(self, db_manager, milvus_client, repo_id, count=3, dim=8):
        svc = ChunkService(db_manager, milvus_client)
        batch_id = str(uuid.uuid4())
        embedder = MockEmbeddingProvider(dimension=dim)
        chunks = []
        for i in range(count):
            chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "repository_id": repo_id,
                "branch": "main",
                "file_path": f"file{i}.py",
                "start_line": 1,
                "end_line": 10,
                "content": f"unique content {uuid.uuid4().hex}",
                "language": "python",
                "chunk_hash": f"hash-{uuid.uuid4().hex}",
            })
        svc.write_staging(batch_id, chunks)
        texts = [c["content"] for c in chunks]
        embeddings = embedder.embed_batch(texts)
        svc.write_staging_embeddings(batch_id, 0, embeddings)
        return svc, batch_id

    def test_move_to_final(self, db_manager, milvus_client):
        repo = create_repository(db_manager)
        svc, batch_id = self._stage_with_embeddings(db_manager, milvus_client, repo.id)
        count = svc.move_to_final(batch_id)
        assert count == 3
        with db_manager.connection_context():
            assert Chunk.select().where(Chunk.repository == repo.id).count() == 3
            assert StagingChunk.select().where(StagingChunk.batch_id == batch_id).count() == 0

    def test_delete_by_branch(self, db_manager, milvus_client):
        repo = create_repository(db_manager)
        svc, batch_id = self._stage_with_embeddings(db_manager, milvus_client, repo.id)
        svc.move_to_final(batch_id)
        deleted = svc.delete_by_branch(repo.id, "main")
        assert deleted == 3
        with db_manager.connection_context():
            assert Chunk.select().where(Chunk.repository == repo.id).count() == 0

    def test_delete_by_files(self, db_manager, milvus_client):
        repo = create_repository(db_manager)
        svc, batch_id = self._stage_with_embeddings(db_manager, milvus_client, repo.id, count=3)
        svc.move_to_final(batch_id)
        deleted = svc.delete_by_files(repo.id, "main", ["file0.py"])
        assert deleted == 1
        with db_manager.connection_context():
            assert Chunk.select().where(Chunk.repository == repo.id).count() == 2

    def test_publish_incremental_batch_skips_missing_embeddings(self, db_manager, milvus_client):
        repo = create_repository(db_manager)
        svc = ChunkService(db_manager, milvus_client)
        batch_id = str(uuid.uuid4())
        svc.write_staging(
            batch_id,
            [
                {
                    "chunk_id": str(uuid.uuid4()),
                    "repository_id": repo.id,
                    "branch": "main",
                    "file_path": "file0.py",
                    "start_line": 1,
                    "end_line": 10,
                    "content": "content without embedding",
                    "language": "python",
                    "chunk_hash": f"hash-{uuid.uuid4().hex}",
                }
            ],
        )

        cleanup_targets = svc.publish_incremental_batch(
            batch_id=batch_id,
            repository_id=repo.id,
            branch="main",
            changed_files=["file0.py"],
        )

        assert cleanup_targets == []
        with db_manager.connection_context():
            indexed_file = IndexedFile.get(
                IndexedFile.repository == repo.id,
                IndexedFile.branch_name == "main",
                IndexedFile.file_path == "file0.py",
            )
            chunk = Chunk.get(
                Chunk.repository == repo.id,
                Chunk.branch == "main",
                Chunk.file_path == "file0.py",
            )
            assert indexed_file.active_publish_id == batch_id
            assert chunk.publish_id == batch_id

    def test_delete_by_publish_targets_skips_none_publish_ids(self, db_manager, milvus_client):
        repo = create_repository(db_manager)
        svc, batch_id = self._stage_with_embeddings(db_manager, milvus_client, repo.id, count=1)
        svc.move_to_final(batch_id)

        deleted = svc.delete_by_publish_targets(
            repository_id=repo.id,
            branch="main",
            cleanup_targets=[
                FilePublishCleanupTarget(
                    file_path="file0.py",
                    previous_publish_id=None,
                )
            ],
        )

        assert deleted == 0
        with db_manager.connection_context():
            assert (
                Chunk.select()
                .where(
                    Chunk.repository == repo.id,
                    Chunk.branch == "main",
                    Chunk.file_path == "file0.py",
                )
                .count()
                == 1
            )
