import pytest
from peewee import IntegrityError
from db import Chunk, IndexedBranch, IndexedFile, Repository, StagingChunk

@pytest.mark.integration
class TestIndexedBranch:
    def _make_repo(self, db_manager, suffix=""):
        with db_manager.connection_context():
            return Repository.create(
                github_repo_id=3000 + hash(suffix) % 1000, full_name=f"o/r{suffix}",
                repo_url="u", display_name="r", owner_login="o", owner_type="User",
            )

    def test_create(self, db_manager):
        repo = self._make_repo(db_manager, "ib1")
        with db_manager.connection_context():
            ib = IndexedBranch.create(repository=repo, branch_name="main")
            assert ib.status == "pending"
            assert ib.target_commit is None
            assert ib.last_indexed_commit is None

    def test_unique_repo_branch(self, db_manager):
        repo = self._make_repo(db_manager, "ib2")
        with db_manager.connection_context():
            IndexedBranch.create(repository=repo, branch_name="main")
            with pytest.raises(IntegrityError):
                IndexedBranch.create(repository=repo, branch_name="main")

    def test_cascade_on_repo_delete(self, db_manager):
        repo = self._make_repo(db_manager, "ib3")
        with db_manager.connection_context():
            IndexedBranch.create(repository=repo, branch_name="main")
            repo.delete_instance()
            assert IndexedBranch.select().count() == 0

@pytest.mark.integration
class TestChunkModel:
    def _make_repo(self, db_manager, suffix=""):
        with db_manager.connection_context():
            return Repository.create(
                github_repo_id=4000 + hash(suffix) % 1000, full_name=f"o/c{suffix}",
                repo_url="u", display_name="r", owner_login="o", owner_type="User",
            )

    def test_create(self, db_manager):
        repo = self._make_repo(db_manager, "c1")
        with db_manager.connection_context():
            chunk = Chunk.create(
                repository=repo, branch="main", file_path="test.py",
                start_line=1, end_line=10, content="code", chunk_hash="abc",
            )
            assert chunk.id is not None
            assert chunk.language is None
            assert chunk.publish_id == "legacy"

    def test_cascade_on_repo_delete(self, db_manager):
        repo = self._make_repo(db_manager, "c2")
        with db_manager.connection_context():
            Chunk.create(repository=repo, branch="main", file_path="t.py", start_line=1, end_line=1, content="x", chunk_hash="h")
            repo.delete_instance()
            assert Chunk.select().count() == 0

@pytest.mark.integration
class TestIndexedFileModel:
    def _make_repo(self, db_manager, suffix=""):
        with db_manager.connection_context():
            return Repository.create(
                github_repo_id=5000 + hash(suffix) % 1000, full_name=f"o/f{suffix}",
                repo_url="u", display_name="r", owner_login="o", owner_type="User",
            )

    def test_unique_repo_branch_file(self, db_manager):
        repo = self._make_repo(db_manager, "f1")
        with db_manager.connection_context():
            IndexedFile.create(repository=repo, branch_name="main", file_path="a.py")
            with pytest.raises(IntegrityError):
                IndexedFile.create(repository=repo, branch_name="main", file_path="a.py")

@pytest.mark.integration
class TestStagingChunkModel:
    def test_create(self, db_manager):
        with db_manager.connection_context():
            sc = StagingChunk.create(
                batch_id="batch-1", seq_index=0, repository_id="repo-1",
                branch="main", file_path="f.py", start_line=1, end_line=5,
                content="code", chunk_hash="h1",
            )
            assert sc.id is not None
            assert sc.embedding is None

    def test_query_by_batch_id(self, db_manager):
        with db_manager.connection_context():
            for i in range(5):
                StagingChunk.create(
                    batch_id="batch-2", seq_index=i, repository_id="repo-1",
                    branch="main", file_path="f.py", start_line=i, end_line=i+1,
                    content=f"line {i}", chunk_hash=f"h{i}",
                )
            StagingChunk.create(
                batch_id="other", seq_index=0, repository_id="repo-1",
                branch="main", file_path="f.py", start_line=0, end_line=1,
                content="other", chunk_hash="ho",
            )
            results = StagingChunk.select().where(StagingChunk.batch_id == "batch-2")
            assert results.count() == 5
