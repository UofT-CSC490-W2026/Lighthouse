from __future__ import annotations

import asyncio
import hashlib
import hmac
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from embedding import OPENAI_DEFAULT_EMBEDDING_MODEL
from fastapi import HTTPException

from db.database import DatabaseManager
from ingestion.chunking.registry import Chunker, ChunkerStrategy, get_chunker, register_chunker
from ingestion.embedding.registry import (
    EmbeddingStrategy,
    get_embedding_provider,
    register_embedding_provider,
)
from ingestion.main import github_webhook
from ingestion.main import lifespan as ingestion_lifespan
from ingestion.temporal.activities.chunking import chunk_files
from ingestion.temporal.activities.inputs import ChunkFilesInput
from ingestion.temporal.activities.helpers import get_settings as activity_get_settings
from ingestion.temporal.activities.helpers import make_db, make_milvus, set_settings_factory
from ingestion.temporal.worker import main as worker_main
from ingestion.utilities.services.chunk import ChunkService


class DummyChunker(Chunker):
    def chunk_file(self, content: str, file_path: str):
        return []


@pytest.mark.unit
def test_database_configure_trims_values():
    manager = DatabaseManager()
    manager.configure("  postgres://trimmed  ")
    assert manager.database_url == "postgres://trimmed"


@pytest.mark.unit
def test_chunker_registry_registers_and_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown chunker strategy"):
        get_chunker("missing")  # type: ignore[arg-type]

    register_chunker(ChunkerStrategy.SLIDING_WINDOW, DummyChunker)
    assert isinstance(get_chunker(ChunkerStrategy.SLIDING_WINDOW), DummyChunker)


@pytest.mark.unit
def test_embedding_registry_registers_and_rejects_unknown():
    class DummyProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    with pytest.raises(ValueError, match="Unknown embedding strategy"):
        get_embedding_provider("missing")  # type: ignore[arg-type]

    register_embedding_provider(EmbeddingStrategy.OPENAI, DummyProvider)  # type: ignore[arg-type]
    provider = get_embedding_provider(EmbeddingStrategy.OPENAI, api_key="key")
    assert provider.kwargs == {
        "api_key": "key",
        "model": OPENAI_DEFAULT_EMBEDDING_MODEL,
    }


@pytest.mark.unit
def test_chunk_service_requires_milvus():
    service = ChunkService(MagicMock(), milvus=None)

    with pytest.raises(RuntimeError, match="MilvusClient not provided"):
        service.move_to_final("batch")


@pytest.mark.unit
def test_chunk_service_move_to_final_returns_zero_when_empty():
    @contextmanager
    def connection_context():
        yield

    db = SimpleNamespace(connection_context=connection_context)
    service = ChunkService(db, milvus=MagicMock())
    select_query = MagicMock()
    select_query.where.return_value.order_by.return_value.tuples.return_value = []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("ingestion.utilities.services.chunk.StagingChunk.select", MagicMock(return_value=select_query))
        assert service.move_to_final("batch") == 0


@pytest.mark.unit
def test_chunk_service_move_to_final_skips_missing_embeddings(monkeypatch):
    @contextmanager
    def connection_context():
        yield

    row = SimpleNamespace(
        id="chunk-1",
        embedding=None,
        repository_id="repo-1",
        branch="main",
        file_path="a.py",
        start_line=1,
        end_line=1,
        content="x",
        language="python",
        chunk_hash="hash",
    )
    delete_query = MagicMock()
    delete_query.where.return_value.execute.return_value = 1
    insert_query = MagicMock()
    insert_query.on_conflict_ignore.return_value.execute.return_value = 1
    select_query = MagicMock()
    select_query.where.return_value.order_by.return_value.tuples.return_value = [
        (
            row.id,
            row.repository_id,
            row.branch,
            row.file_path,
            row.start_line,
            row.end_line,
            row.content,
            row.language,
            row.chunk_hash,
            row.embedding,
        )
    ]

    db = SimpleNamespace(connection_context=connection_context)
    milvus = MagicMock()
    service = ChunkService(db, milvus=milvus)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("ingestion.utilities.services.chunk.StagingChunk.select", MagicMock(return_value=select_query))
        mp.setattr("ingestion.utilities.services.chunk.StagingChunk.delete", MagicMock(return_value=delete_query))
        mp.setattr("ingestion.utilities.services.chunk.Chunk.insert_many", MagicMock(return_value=insert_query))
        assert service.move_to_final("batch") == 1

    milvus.insert.assert_not_called()


@pytest.mark.unit
def test_chunk_service_move_to_final_inserts_legacy_publish_id_into_milvus():
    @contextmanager
    def connection_context():
        yield

    row = (
        "chunk-1",
        "repo-1",
        "main",
        "a.py",
        1,
        1,
        "x",
        "python",
        "hash",
        b"[0.1, 0.2, 0.3]",
    )
    delete_query = MagicMock()
    delete_query.where.return_value.execute.return_value = 1
    insert_query = MagicMock()
    insert_query.on_conflict_ignore.return_value.execute.return_value = 1
    select_query = MagicMock()
    select_query.where.return_value.order_by.return_value.tuples.return_value = [row]

    db = SimpleNamespace(connection_context=connection_context)
    milvus = MagicMock()
    service = ChunkService(db, milvus=milvus)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("ingestion.utilities.services.chunk.StagingChunk.select", MagicMock(return_value=select_query))
        mp.setattr("ingestion.utilities.services.chunk.StagingChunk.delete", MagicMock(return_value=delete_query))
        mp.setattr("ingestion.utilities.services.chunk.Chunk.insert_many", MagicMock(return_value=insert_query))
        assert service.move_to_final("batch") == 1

    milvus.insert.assert_called_once()
    inserted_batch = milvus.insert.call_args.args[0]
    assert inserted_batch[0]["publish_id"] == "legacy"


@pytest.mark.unit
def test_chunk_files_uses_git_list_and_skips_unreadable_file(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    readable = repo_path / "good.py"
    readable.write_text("print('ok')\n", encoding="utf-8")
    unreadable = repo_path / "bad.py"
    unreadable.write_text("ignored", encoding="utf-8")

    fake_chunk = SimpleNamespace(content="print('ok')\n", start_line=1, end_line=1, chunk_hash="hash")
    chunker = SimpleNamespace(chunk_file=MagicMock(return_value=[fake_chunk]))
    git = SimpleNamespace(list_files=MagicMock(return_value=[readable, unreadable]))
    service = SimpleNamespace(write_staging=MagicMock())
    closed = []

    monkeypatch.setattr("ingestion.temporal.activities.chunking.get_settings", MagicMock(return_value=SimpleNamespace(clone_base_dir=str(tmp_path))))
    monkeypatch.setattr("ingestion.temporal.activities.chunking.make_db", MagicMock(return_value=SimpleNamespace(close=lambda: closed.append(True))))
    monkeypatch.setattr("ingestion.temporal.activities.chunking.get_chunker", MagicMock(return_value=chunker))
    monkeypatch.setattr("ingestion.temporal.activities.chunking.GitOperations", MagicMock(return_value=git))
    monkeypatch.setattr("ingestion.temporal.activities.chunking.ChunkService", MagicMock(return_value=service))

    original_read_text = Path.read_text

    def fake_read_text(path: Path, *args, **kwargs):
        if path == unreadable:
            raise OSError("nope")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    result = asyncio.run(
        chunk_files(
            ChunkFilesInput(
                repository_id="repo-id",
                branch="main",
                repo_path=str(repo_path),
                chunker_strategy="sliding_window",
            )
        )
    )

    assert result.chunk_count == 1
    service.write_staging.assert_called_once()
    assert closed == [True]


@pytest.mark.unit
def test_chunk_files_skips_blank_content(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    blank = repo_path / "blank.py"
    blank.write_text("   \n", encoding="utf-8")

    chunker = SimpleNamespace(chunk_file=MagicMock(return_value=[]))
    git = SimpleNamespace(list_files=MagicMock(return_value=[blank]))
    service = SimpleNamespace(write_staging=MagicMock())

    monkeypatch.setattr("ingestion.temporal.activities.chunking.get_settings", MagicMock(return_value=SimpleNamespace(clone_base_dir=str(tmp_path))))
    monkeypatch.setattr("ingestion.temporal.activities.chunking.make_db", MagicMock(return_value=SimpleNamespace(close=MagicMock())))
    monkeypatch.setattr("ingestion.temporal.activities.chunking.get_chunker", MagicMock(return_value=chunker))
    monkeypatch.setattr("ingestion.temporal.activities.chunking.GitOperations", MagicMock(return_value=git))
    monkeypatch.setattr("ingestion.temporal.activities.chunking.ChunkService", MagicMock(return_value=service))

    result = asyncio.run(
        chunk_files(
            ChunkFilesInput(
                repository_id="repo-id",
                branch="main",
                repo_path=str(repo_path),
                chunker_strategy="sliding_window",
            )
        )
    )

    assert result.chunk_count == 0
    service.write_staging.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_missing_signature_and_fields(monkeypatch):
    app_state = SimpleNamespace(
        settings=SimpleNamespace(github_webhook_secret="secret", temporal_task_queue="queue"),
        temporal_client=SimpleNamespace(start_workflow=AsyncMock()),
    )
    monkeypatch.setattr("ingestion.main.app", SimpleNamespace(state=app_state))

    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {"X-GitHub-Event": "push"}

    with pytest.raises(HTTPException, match="Missing signature"):
        await github_webhook(request)

    body = b'{"ref":"refs/heads/main","repository":{"id":1,"full_name":"owner/repo"}}'
    request.headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(
        b"secret", body, hashlib.sha256
    ).hexdigest()
    request.body = AsyncMock(return_value=body)
    with pytest.raises(HTTPException, match="Missing required webhook fields"):
        await github_webhook(request)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_ignores_non_branch_push(monkeypatch):
    app_state = SimpleNamespace(
        settings=SimpleNamespace(github_webhook_secret=""),
        temporal_client=SimpleNamespace(start_workflow=AsyncMock()),
    )
    monkeypatch.setattr("ingestion.main.app", SimpleNamespace(state=app_state))

    request = MagicMock()
    request.body = AsyncMock(
        return_value=b'{"ref":"refs/tags/v1","before":"a","after":"b","repository":{"id":1,"full_name":"owner/repo"}}'
    )
    request.headers = {"X-GitHub-Event": "push"}

    assert await github_webhook(request) == {"status": "ignored", "reason": "not a branch push"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_temporal_worker_main(monkeypatch):
    settings = SimpleNamespace(temporal_address="temporal:7233", temporal_task_queue="queue")
    client = object()
    worker = SimpleNamespace(run=AsyncMock())
    worker_cls = MagicMock(return_value=worker)

    monkeypatch.setattr("ingestion.temporal.worker.IngestionSettings", MagicMock(return_value=settings))
    monkeypatch.setattr("ingestion.temporal.worker.Client.connect", AsyncMock(return_value=client))
    monkeypatch.setattr("ingestion.temporal.worker.Worker", worker_cls)

    await worker_main()

    worker_cls.assert_called_once()
    worker.run.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingestion_lifespan_and_activity_helpers(monkeypatch):
    settings = SimpleNamespace(temporal_address="temporal:7233", postgres_dsn="postgres://db", milvus_uri="http://milvus")
    app = SimpleNamespace(state=SimpleNamespace())
    client = object()
    db = MagicMock()
    milvus = MagicMock()

    monkeypatch.setattr("ingestion.main.IngestionSettings", MagicMock(return_value=settings))
    monkeypatch.setattr("ingestion.main.Client.connect", AsyncMock(return_value=client))

    async with ingestion_lifespan(app):
        assert app.state.settings is settings
        assert app.state.temporal_client is client

    set_settings_factory(lambda: settings)
    assert activity_get_settings() is settings
    set_settings_factory(None)
    monkeypatch.setattr("ingestion.temporal.activities.helpers.IngestionSettings", MagicMock(return_value=settings))
    assert activity_get_settings() is settings

    monkeypatch.setattr("ingestion.temporal.activities.helpers.DatabaseManager", MagicMock(return_value=db))
    assert make_db(settings) is db
    db.connect.assert_called_once_with()

    monkeypatch.setattr("ingestion.temporal.activities.helpers.MilvusClient", MagicMock(return_value=milvus))
    assert make_milvus(settings) is milvus
    milvus.ensure_collection.assert_called_once()
