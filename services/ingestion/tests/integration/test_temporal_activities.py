"""Integration tests for Temporal activities using ActivityEnvironment.

Each activity is run via ``activity_environment.run()`` with real Postgres
and Milvus testcontainers. Git and embedding operations are mocked.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from db import Chunk, IndexedBranch, IndexedFile, Repository, StagingChunk

from ingestion.temporal.activities.branch import update_branch_status
from ingestion.temporal.activities.chunking import chunk_files
from ingestion.temporal.activities.embedding import embed_chunk_batch
from ingestion.temporal.activities.git import get_changed_files, git_clone_or_fetch
from ingestion.temporal.activities.inputs import (
    CleanupInactiveChunksInput,
    ChunkFilesInput,
    CleanupStagingInput,
    DeleteChunksForFilesInput,
    DeleteChunksInput,
    EmbedBatchInput,
    EnsureRepoInput,
    FilePublishCleanup,
    GetChangedFilesInput,
    GitCloneFetchInput,
    PublishStagedChunksInput,
    StoreChunksInput,
    UpdateBranchStatusInput,
)
from ingestion.temporal.activities.repository import ensure_repository_record
from ingestion.temporal.activities.storage import (
    cleanup_inactive_chunks,
    cleanup_staging,
    delete_chunks_for_files,
    delete_existing_chunks,
    publish_staged_chunks,
    store_chunks,
)
from testing_utils.factories import create_repository, create_staging_chunk
from testing_utils.mock_embedding import MockEmbeddingProvider

TEST_DIM = 8


def _reconnect(db_manager):
    """Re-bind the Peewee proxy after an activity has closed its own DatabaseManager.

    Activities create a separate DatabaseManager whose connect() rebinds the
    global DatabaseProxy. When that activity's db.close() runs, the proxy
    points at a closed database even though *our* db_manager's _database is
    still open. Force re-initialization to rebind the proxy.
    """
    db_manager._database = None  # noqa: SLF001
    db_manager.connect()


def _seed_staging_with_embeddings(db_manager, repo, batch_id, count=3):
    """Create staging chunks with embeddings for store_chunks tests."""
    embedder = MockEmbeddingProvider(dimension=TEST_DIM)
    for i in range(count):
        content = f"chunk content {i}"
        emb = embedder.embed_batch([content])[0]
        create_staging_chunk(
            db_manager,
            batch_id=batch_id,
            seq_index=i,
            repository_id=repo.id,
            content=content,
            embedding=json.dumps(emb).encode("utf-8"),
            file_path=f"file{i}.py",
        )


# ---------------------------------------------------------------------------
# ensure_repository_record
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEnsureRepositoryRecord:
    async def test_creates_new_repository(
        self, activity_environment, db_manager, inject_settings
    ):
        result = await activity_environment.run(
            ensure_repository_record,
            EnsureRepoInput(
                github_repo_id=12345,
                repo_url="https://github.com/owner/repo",
                full_name="owner/repo",
            ),
        )
        assert result  # non-empty string id
        _reconnect(db_manager)
        with db_manager.connection_context():
            repo = Repository.get_by_id(result)
            assert repo.github_repo_id == 12345

    async def test_returns_existing_on_duplicate(
        self, activity_environment, db_manager, inject_settings
    ):
        inp = EnsureRepoInput(
            github_repo_id=99999,
            repo_url="https://github.com/o/r",
            full_name="o/r",
        )
        id1 = await activity_environment.run(ensure_repository_record, inp)
        id2 = await activity_environment.run(ensure_repository_record, inp)
        assert id1 == id2


# ---------------------------------------------------------------------------
# update_branch_status
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUpdateBranchStatus:
    async def test_sets_indexing_status(
        self, activity_environment, db_manager, inject_settings
    ):
        repo = create_repository(db_manager)
        await activity_environment.run(
            update_branch_status,
            UpdateBranchStatusInput(
                repository_id=repo.id, branch="main", status="indexing"
            ),
        )
        _reconnect(db_manager)
        with db_manager.connection_context():
            ib = IndexedBranch.get(
                IndexedBranch.repository == repo,
                IndexedBranch.branch_name == "main",
            )
            assert ib.status == "indexing"

    async def test_updates_to_indexed_with_commit(
        self, activity_environment, db_manager, inject_settings
    ):
        repo = create_repository(db_manager)
        await activity_environment.run(
            update_branch_status,
            UpdateBranchStatusInput(
                repository_id=repo.id, branch="main", status="indexing"
            ),
        )
        await activity_environment.run(
            update_branch_status,
            UpdateBranchStatusInput(
                repository_id=repo.id,
                branch="main",
                status="indexed",
                latest_commit="abc123",
            ),
        )
        _reconnect(db_manager)
        with db_manager.connection_context():
            ib = IndexedBranch.get(
                IndexedBranch.repository == repo,
                IndexedBranch.branch_name == "main",
            )
            assert ib.status == "indexed"
            assert ib.last_indexed_commit == "abc123"

    async def test_sets_failed_status(
        self, activity_environment, db_manager, inject_settings
    ):
        repo = create_repository(db_manager)
        await activity_environment.run(
            update_branch_status,
            UpdateBranchStatusInput(
                repository_id=repo.id, branch="main", status="indexing"
            ),
        )
        await activity_environment.run(
            update_branch_status,
            UpdateBranchStatusInput(
                repository_id=repo.id, branch="main", status="failed"
            ),
        )
        _reconnect(db_manager)
        with db_manager.connection_context():
            ib = IndexedBranch.get(
                IndexedBranch.repository == repo,
                IndexedBranch.branch_name == "main",
            )
            assert ib.status == "failed"


# ---------------------------------------------------------------------------
# git_clone_or_fetch
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGitCloneOrFetch:
    async def test_returns_path_and_commit(
        self, activity_environment, inject_settings
    ):
        mock_git = MagicMock()
        mock_git.clone_or_fetch.return_value = Path("/tmp/repos/12345")
        mock_git.get_latest_commit.return_value = "deadbeef"

        with patch(
            "ingestion.temporal.activities.git.GitOperations",
            return_value=mock_git,
        ):
            result = await activity_environment.run(
                git_clone_or_fetch,
                GitCloneFetchInput(
                    repo_url="https://github.com/o/r",
                    repo_dir_name="12345",
                    branch="main",
                ),
            )
        assert result.repo_path == "/tmp/repos/12345"
        assert result.latest_commit == "deadbeef"


# ---------------------------------------------------------------------------
# get_changed_files
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetChangedFiles:
    async def test_returns_changed_file_paths(
        self, activity_environment, inject_settings, tmp_path
    ):
        mock_git = MagicMock()
        mock_git.get_changed_files.return_value = [
            tmp_path / "a.py",
            tmp_path / "b.py",
        ]

        with patch(
            "ingestion.temporal.activities.git.GitOperations",
            return_value=mock_git,
        ):
            result = await activity_environment.run(
                get_changed_files,
                GetChangedFilesInput(
                    repo_path=str(tmp_path),
                    before_commit="aaa",
                    after_commit="bbb",
                ),
            )
        assert result == ["a.py", "b.py"]

    async def test_returns_empty_when_no_changes(
        self, activity_environment, inject_settings, tmp_path
    ):
        mock_git = MagicMock()
        mock_git.get_changed_files.return_value = []

        with patch(
            "ingestion.temporal.activities.git.GitOperations",
            return_value=mock_git,
        ):
            result = await activity_environment.run(
                get_changed_files,
                GetChangedFilesInput(
                    repo_path=str(tmp_path),
                    before_commit="aaa",
                    after_commit="bbb",
                ),
            )
        assert result == []


# ---------------------------------------------------------------------------
# chunk_files
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChunkFiles:
    async def test_chunks_written_to_staging(
        self, activity_environment, db_manager, inject_settings, tmp_path
    ):
        repo = create_repository(db_manager)
        # Create a Python file with enough content to produce at least one chunk
        py_file = tmp_path / "hello.py"
        py_file.write_text("def hello():\n    return 'world'\n")

        result = await activity_environment.run(
            chunk_files,
            ChunkFilesInput(
                repo_path=str(tmp_path),
                repository_id=repo.id,
                branch="main",
                file_filter=["hello.py"],
            ),
        )
        assert result.chunk_count > 0
        _reconnect(db_manager)
        with db_manager.connection_context():
            staging = list(
                StagingChunk.select().where(
                    StagingChunk.batch_id == result.batch_id
                )
            )
            assert len(staging) == result.chunk_count

    async def test_empty_repo_zero_chunks(
        self, activity_environment, db_manager, inject_settings, tmp_path
    ):
        repo = create_repository(db_manager)
        result = await activity_environment.run(
            chunk_files,
            ChunkFilesInput(
                repo_path=str(tmp_path),
                repository_id=repo.id,
                branch="main",
                file_filter=[],  # no files
            ),
        )
        assert result.chunk_count == 0

    async def test_file_filter_limits_processing(
        self, activity_environment, db_manager, inject_settings, tmp_path
    ):
        repo = create_repository(db_manager)
        (tmp_path / "a.py").write_text("def a():\n    pass\n")
        (tmp_path / "b.py").write_text("def b():\n    pass\n")

        result = await activity_environment.run(
            chunk_files,
            ChunkFilesInput(
                repo_path=str(tmp_path),
                repository_id=repo.id,
                branch="main",
                file_filter=["a.py"],
            ),
        )
        assert result.chunk_count > 0
        _reconnect(db_manager)
        with db_manager.connection_context():
            staging = list(
                StagingChunk.select().where(
                    StagingChunk.batch_id == result.batch_id
                )
            )
            file_paths = {s.file_path for s in staging}
            assert file_paths == {"a.py"}


# ---------------------------------------------------------------------------
# embed_chunk_batch
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEmbedChunkBatch:
    async def test_embeds_and_writes_vectors(
        self, activity_environment, db_manager, inject_settings
    ):
        repo = create_repository(db_manager)
        batch_id = str(uuid.uuid4())
        for i in range(3):
            create_staging_chunk(
                db_manager,
                batch_id=batch_id,
                seq_index=i,
                repository_id=repo.id,
                content=f"chunk {i}",
            )

        with patch(
            "ingestion.temporal.activities.embedding.get_embedding_provider",
            return_value=MockEmbeddingProvider(dimension=TEST_DIM),
        ):
            result = await activity_environment.run(
                embed_chunk_batch,
                EmbedBatchInput(batch_id=batch_id, offset=0, limit=10),
            )
        assert result == "embedded_3"
        _reconnect(db_manager)
        with db_manager.connection_context():
            rows = list(
                StagingChunk.select()
                .where(StagingChunk.batch_id == batch_id)
                .order_by(StagingChunk.seq_index)
            )
            for row in rows:
                assert row.embedding is not None

    async def test_no_chunks_returns_marker(
        self, activity_environment, db_manager, inject_settings
    ):
        with patch(
            "ingestion.temporal.activities.embedding.get_embedding_provider",
            return_value=MockEmbeddingProvider(dimension=TEST_DIM),
        ):
            result = await activity_environment.run(
                embed_chunk_batch,
                EmbedBatchInput(
                    batch_id=str(uuid.uuid4()), offset=0, limit=10
                ),
            )
        assert result == "no_chunks"


# ---------------------------------------------------------------------------
# store_chunks
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreChunks:
    async def test_moves_staging_to_final(
        self, activity_environment, db_manager, milvus_client, inject_settings
    ):
        repo = create_repository(db_manager)
        batch_id = str(uuid.uuid4())
        _seed_staging_with_embeddings(db_manager, repo, batch_id, count=2)

        with patch(
            "ingestion.temporal.activities.helpers.EMBEDDING_DIMENSION",
            TEST_DIM,
        ), patch(
            "ingestion.temporal.activities.helpers.MILVUS_COLLECTION_NAME",
            "test_embeddings",
        ):
            count = await activity_environment.run(
                store_chunks,
                StoreChunksInput(batch_id=batch_id),
            )
        assert count == 2
        _reconnect(db_manager)
        with db_manager.connection_context():
            assert Chunk.select().where(Chunk.repository == repo).count() == 2
            assert (
                StagingChunk.select()
                .where(StagingChunk.batch_id == batch_id)
                .count()
                == 0
            )
            assert Chunk.get(Chunk.repository == repo).publish_id == "legacy"


# ---------------------------------------------------------------------------
# publish_staged_chunks
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPublishStagedChunks:
    async def test_switches_active_publish_without_deleting_old_rows(
        self, activity_environment, db_manager, milvus_client, inject_settings
    ):
        repo = create_repository(db_manager)
        old_publish_id = "legacy"
        with db_manager.connection_context():
            Chunk.create(
                repository=repo,
                branch="main",
                file_path="file0.py",
                start_line=1,
                end_line=5,
                content="old chunk",
                chunk_hash="old-hash",
                publish_id=old_publish_id,
            )
            IndexedFile.create(
                repository=repo,
                branch_name="main",
                file_path="file0.py",
                active_publish_id=old_publish_id,
            )

        milvus_client.insert(
            [
                {
                    "id": "legacy-file0",
                    "chunk_id": "legacy-file0",
                    "embedding": [0.1] * TEST_DIM,
                    "repository_id": repo.id,
                    "file_path": "file0.py",
                    "branch": "main",
                    "publish_id": old_publish_id,
                }
            ]
        )

        batch_id = str(uuid.uuid4())
        create_staging_chunk(
            db_manager,
            batch_id=batch_id,
            seq_index=0,
            repository_id=repo.id,
            file_path="file0.py",
            content="new chunk",
            embedding=json.dumps([0.2] * TEST_DIM).encode("utf-8"),
        )
        with db_manager.connection_context():
            IndexedFile.create(
                repository=repo,
                branch_name="main",
                file_path="deleted.py",
                active_publish_id=old_publish_id,
            )

        with patch(
            "ingestion.temporal.activities.helpers.EMBEDDING_DIMENSION",
            TEST_DIM,
        ), patch(
            "ingestion.temporal.activities.helpers.MILVUS_COLLECTION_NAME",
            "test_embeddings",
        ):
            result = await activity_environment.run(
                publish_staged_chunks,
                PublishStagedChunksInput(
                    batch_id=batch_id,
                    repository_id=repo.id,
                    branch="main",
                    changed_files=["file0.py", "deleted.py"],
                ),
            )

        _reconnect(db_manager)
        with db_manager.connection_context():
            active_file = IndexedFile.get(
                IndexedFile.repository == repo,
                IndexedFile.branch_name == "main",
                IndexedFile.file_path == "file0.py",
            )
            hidden_file = IndexedFile.get(
                IndexedFile.repository == repo,
                IndexedFile.branch_name == "main",
                IndexedFile.file_path == "deleted.py",
            )
            assert active_file.active_publish_id == batch_id
            assert hidden_file.active_publish_id is None
            assert (
                Chunk.select()
                .where(Chunk.repository == repo, Chunk.file_path == "file0.py")
                .count()
                == 2
            )
            assert (
                StagingChunk.select()
                .where(StagingChunk.batch_id == batch_id)
                .count()
                == 0
            )

        assert {target.file_path for target in result.cleanup_targets} == {
            "file0.py",
            "deleted.py",
        }


# ---------------------------------------------------------------------------
# cleanup_inactive_chunks
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanupInactiveChunks:
    async def test_deletes_only_stale_publish(
        self, activity_environment, db_manager, milvus_client, inject_settings
    ):
        repo = create_repository(db_manager)
        with db_manager.connection_context():
            Chunk.create(
                id="legacy-id",
                repository=repo,
                branch="main",
                file_path="file0.py",
                start_line=1,
                end_line=5,
                content="old chunk",
                chunk_hash="old-hash",
                publish_id="legacy",
            )
            Chunk.create(
                id="new-id",
                repository=repo,
                branch="main",
                file_path="file0.py",
                start_line=1,
                end_line=5,
                content="new chunk",
                chunk_hash="new-hash",
                publish_id="batch-123",
            )

        milvus_client.insert(
            [
                {
                    "id": "legacy-id",
                    "chunk_id": "legacy-id",
                    "embedding": [0.1] * TEST_DIM,
                    "repository_id": repo.id,
                    "file_path": "file0.py",
                    "branch": "main",
                    "publish_id": "legacy",
                },
                {
                    "id": "new-id",
                    "chunk_id": "new-id",
                    "embedding": [0.2] * TEST_DIM,
                    "repository_id": repo.id,
                    "file_path": "file0.py",
                    "branch": "main",
                    "publish_id": "batch-123",
                },
            ]
        )

        with patch(
            "ingestion.temporal.activities.helpers.EMBEDDING_DIMENSION",
            TEST_DIM,
        ), patch(
            "ingestion.temporal.activities.helpers.MILVUS_COLLECTION_NAME",
            "test_embeddings",
        ):
            deleted = await activity_environment.run(
                cleanup_inactive_chunks,
                CleanupInactiveChunksInput(
                    repository_id=repo.id,
                    branch="main",
                    cleanup_targets=[
                        FilePublishCleanup(
                            file_path="file0.py",
                            previous_publish_id="legacy",
                        )
                    ],
                ),
            )

        assert deleted == 1
        _reconnect(db_manager)
        with db_manager.connection_context():
            remaining = list(
                Chunk.select().where(
                    Chunk.repository == repo,
                    Chunk.branch == "main",
                    Chunk.file_path == "file0.py",
                )
            )
            assert len(remaining) == 1
            assert remaining[0].publish_id == "batch-123"


# ---------------------------------------------------------------------------
# delete_existing_chunks
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteExistingChunks:
    async def test_deletes_all_branch_chunks(
        self, activity_environment, db_manager, milvus_client, inject_settings
    ):
        repo = create_repository(db_manager)
        batch_id = str(uuid.uuid4())
        _seed_staging_with_embeddings(db_manager, repo, batch_id, count=2)

        # Move to final first so there's data to delete
        with patch(
            "ingestion.temporal.activities.helpers.EMBEDDING_DIMENSION",
            TEST_DIM,
        ), patch(
            "ingestion.temporal.activities.helpers.MILVUS_COLLECTION_NAME",
            "test_embeddings",
        ):
            await activity_environment.run(
                store_chunks,
                StoreChunksInput(batch_id=batch_id),
            )
            deleted = await activity_environment.run(
                delete_existing_chunks,
                DeleteChunksInput(repository_id=repo.id, branch="main"),
            )
        assert deleted >= 2
        _reconnect(db_manager)
        with db_manager.connection_context():
            assert (
                Chunk.select()
                .where(Chunk.repository == repo, Chunk.branch == "main")
                .count()
                == 0
            )


# ---------------------------------------------------------------------------
# delete_chunks_for_files
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteChunksForFiles:
    async def test_deletes_specific_file_chunks(
        self, activity_environment, db_manager, milvus_client, inject_settings
    ):
        repo = create_repository(db_manager)
        batch_id = str(uuid.uuid4())
        _seed_staging_with_embeddings(db_manager, repo, batch_id, count=3)

        with patch(
            "ingestion.temporal.activities.helpers.EMBEDDING_DIMENSION",
            TEST_DIM,
        ), patch(
            "ingestion.temporal.activities.helpers.MILVUS_COLLECTION_NAME",
            "test_embeddings",
        ):
            await activity_environment.run(
                store_chunks,
                StoreChunksInput(batch_id=batch_id),
            )
            deleted = await activity_environment.run(
                delete_chunks_for_files,
                DeleteChunksForFilesInput(
                    repository_id=repo.id,
                    branch="main",
                    file_paths=["file0.py"],
                ),
            )
        assert deleted >= 1
        _reconnect(db_manager)
        with db_manager.connection_context():
            remaining = list(
                Chunk.select().where(
                    Chunk.repository == repo, Chunk.branch == "main"
                )
            )
            for c in remaining:
                assert c.file_path != "file0.py"


# ---------------------------------------------------------------------------
# cleanup_staging
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanupStaging:
    async def test_removes_staging_rows(
        self, activity_environment, db_manager, inject_settings
    ):
        repo = create_repository(db_manager)
        batch_id = str(uuid.uuid4())
        for i in range(3):
            create_staging_chunk(
                db_manager,
                batch_id=batch_id,
                seq_index=i,
                repository_id=repo.id,
            )

        result = await activity_environment.run(
            cleanup_staging,
            CleanupStagingInput(batch_id=batch_id),
        )
        assert result == "cleaned"
        _reconnect(db_manager)
        with db_manager.connection_context():
            assert (
                StagingChunk.select()
                .where(StagingChunk.batch_id == batch_id)
                .count()
                == 0
            )
