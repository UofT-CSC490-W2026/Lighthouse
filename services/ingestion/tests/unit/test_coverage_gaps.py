from __future__ import annotations

import asyncio
import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from embedding import OPENAI_DEFAULT_EMBEDDING_MODEL
from fastapi import HTTPException

from db.database import DatabaseManager
from ingestion.chunking.registry import Chunker, ChunkerStrategy, get_chunker, register_chunker
from ingestion.chunking.sliding_window_chunker import SlidingWindowChunker
from ingestion.embedding.registry import (
    EmbeddingStrategy,
    get_embedding_provider,
    register_embedding_provider,
)
from ingestion.main import _ensure_repository_record
from ingestion.main import github_webhook
from ingestion.main import lifespan as ingestion_lifespan
from ingestion.chunking.ast_code_chunker import ASTCodeChunker
from ingestion.temporal.activities.chunking import chunk_files
from ingestion.temporal.activities.embedding import embed_chunk_batch
from ingestion.temporal.activities.inputs import ChunkFilesInput
from ingestion.temporal.activities.inputs import EmbedBatchInput
from ingestion.temporal.activities.helpers import get_settings as activity_get_settings
from ingestion.temporal.activities.helpers import make_db, make_milvus, set_settings_factory
from ingestion.temporal.worker import main as worker_main
from ingestion.utilities.config import IngestionSettings
from ingestion.utilities.services.chunk import ChunkService


class DummyChunker(Chunker):
    def chunk_file(self, content: str, file_path: str, language: str | None = None):
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
    try:
        assert isinstance(get_chunker(ChunkerStrategy.SLIDING_WINDOW), DummyChunker)
    finally:
        register_chunker(ChunkerStrategy.SLIDING_WINDOW, SlidingWindowChunker)


@pytest.mark.unit
def test_chunker_registry_passes_language_to_ast_chunker():
    chunker = get_chunker(ChunkerStrategy.AST_CODE, language="python")

    assert isinstance(chunker, ASTCodeChunker)
    assert chunker.default_language == "python"


@pytest.mark.unit
def test_embedding_registry_registers_and_rejects_unknown():
    class DummyProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    with pytest.raises(ValueError, match="Unknown embedding strategy"):
        get_embedding_provider("missing")  # type: ignore[arg-type]

    register_embedding_provider(EmbeddingStrategy.OPENAI, DummyProvider)  # type: ignore[arg-type]
    provider = get_embedding_provider(EmbeddingStrategy.OPENAI, api_key="key")
    assert provider.kwargs == {"api_key": "key"}


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
def test_chunk_files_ast_falls_back_sliding_for_unsupported_ast_language(monkeypatch, tmp_path):
    """astchunk rejects some detected languages (e.g. toml); chunk_file fallback must run."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    toml_file = repo_path / "pyproject.toml"
    toml_file.write_text("[project]\nname = \"x\"\n", encoding="utf-8")

    service = SimpleNamespace(write_staging=MagicMock())
    closed: list[bool] = []

    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.get_settings",
        MagicMock(return_value=SimpleNamespace(clone_base_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.make_db",
        MagicMock(return_value=SimpleNamespace(close=lambda: closed.append(True))),
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.ChunkService",
        MagicMock(return_value=service),
    )

    result = asyncio.run(
        chunk_files(
            ChunkFilesInput(
                repository_id="repo-id",
                branch="main",
                repo_path=str(repo_path),
                chunker_strategy="ast_code",
                file_filter=["pyproject.toml"],
            )
        )
    )

    assert result.chunk_count >= 1
    service.write_staging.assert_called_once()
    assert closed == [True]


@pytest.mark.unit
def test_chunk_files_ast_falls_back_when_get_chunker_raises(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    py_file = repo_path / "a.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    service = SimpleNamespace(write_staging=MagicMock())
    closed: list[bool] = []

    def boom_get_chunker(strategy, language=None, chunker_config=None):
        if strategy is ChunkerStrategy.AST_CODE:
            raise ValueError("AST chunker construction failed")
        return get_chunker(strategy, language=language, chunker_config=chunker_config)

    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.get_settings",
        MagicMock(return_value=SimpleNamespace(clone_base_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.make_db",
        MagicMock(return_value=SimpleNamespace(close=lambda: closed.append(True))),
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.get_chunker",
        boom_get_chunker,
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.ChunkService",
        MagicMock(return_value=service),
    )

    result = asyncio.run(
        chunk_files(
            ChunkFilesInput(
                repository_id="repo-id",
                branch="main",
                repo_path=str(repo_path),
                chunker_strategy="ast_code",
                file_filter=["a.py"],
            )
        )
    )

    assert result.chunk_count >= 1
    service.write_staging.assert_called_once()
    assert closed == [True]


@pytest.mark.unit
def test_chunk_files_ast_fallbacks_cover_unknown_language_and_runtime_error(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    unknown = repo_path / "notes.txt"
    unknown.write_text("alpha\nbeta\n", encoding="utf-8")
    python_file = repo_path / "hello.py"
    python_file.write_text("def hello():\n    return 1\n", encoding="utf-8")

    fallback_chunk = SimpleNamespace(content="chunked content", start_line=1, end_line=2, chunk_hash="hash")
    service = SimpleNamespace(write_staging=MagicMock())
    closed = []

    class FakeSlidingWindowChunker:
        def chunk_file(self, content: str, file_path: str, language: str | None = None):
            return [fallback_chunk]

    class FakeAstCodeChunker:
        def chunk_file(self, content: str, file_path: str, language: str | None = None):
            raise RuntimeError("ast boom")

    def fake_get_chunker(strategy, language=None, chunker_config=None):
        if strategy is ChunkerStrategy.SLIDING_WINDOW:
            return FakeSlidingWindowChunker()
        if strategy is ChunkerStrategy.AST_CODE:
            return FakeAstCodeChunker()
        raise AssertionError(f"unexpected strategy: {strategy}")

    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.get_settings",
        MagicMock(return_value=SimpleNamespace(clone_base_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.make_db",
        MagicMock(return_value=SimpleNamespace(close=lambda: closed.append(True))),
    )
    monkeypatch.setattr("ingestion.temporal.activities.chunking.get_chunker", fake_get_chunker)
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.ChunkService",
        MagicMock(return_value=service),
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.ASTCodeChunker",
        FakeAstCodeChunker,
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.chunking.SlidingWindowChunker",
        FakeSlidingWindowChunker,
    )

    result = asyncio.run(
        chunk_files(
            ChunkFilesInput(
                repository_id="repo-id",
                branch="main",
                repo_path=str(repo_path),
                chunker_strategy="ast_code",
                file_filter=["notes.txt", "hello.py"],
            )
        )
    )

    assert result.chunk_count == 2
    service.write_staging.assert_called_once()
    written_chunks = service.write_staging.call_args.args[1]
    assert len(written_chunks) == 2
    assert {chunk["file_path"] for chunk in written_chunks} == {"notes.txt", "hello.py"}
    assert closed == [True]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_chunk_batch_uses_strategy_specific_default_model(monkeypatch):
    captured: dict[str, object] = {}
    fake_db = SimpleNamespace(close=MagicMock())
    fake_chunk = SimpleNamespace(content="hello world")
    fake_service = SimpleNamespace(
        read_staging_batch=MagicMock(return_value=[fake_chunk]),
        write_staging_embeddings=MagicMock(),
    )
    fake_embedder = SimpleNamespace(embed_batch=MagicMock(return_value=[[0.1] * 8]))

    settings = IngestionSettings(
        embedding_strategy="bedrock",
        embedding_model="",
        embedding_dimension=0,
        openai_api_key="",
    )

    monkeypatch.setattr(
        "ingestion.temporal.activities.embedding.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.embedding.make_db",
        lambda _settings: fake_db,
    )
    monkeypatch.setattr(
        "ingestion.temporal.activities.embedding.ChunkService",
        lambda _db: fake_service,
    )

    def fake_get_embedding_provider(strategy, **kwargs):
        captured["strategy"] = strategy
        captured["kwargs"] = kwargs
        return fake_embedder

    monkeypatch.setattr(
        "ingestion.temporal.activities.embedding.get_embedding_provider",
        fake_get_embedding_provider,
    )

    result = await embed_chunk_batch(
        EmbedBatchInput(
            batch_id="batch-1",
            offset=0,
            limit=1,
            embedding_strategy="bedrock",
        )
    )

    assert result == "embedded_1"
    assert captured["kwargs"] == {
        "model": "amazon.titan-embed-text-v2:0",
        "dimensions": 1024,
    }
    fake_service.write_staging_embeddings.assert_called_once()
    fake_db.close.assert_called_once()


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
    settings = SimpleNamespace(
        temporal_address="temporal:7233",
        postgres_dsn="postgres://db",
        milvus_uri="http://milvus",
        embedding_strategy="openai",
        chunker_strategy="sliding_window",
        embedding_dimension=0,
    )
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


@pytest.mark.unit
def test_ensure_repository_record_connects_and_closes(monkeypatch):
    settings = SimpleNamespace(postgres_dsn="postgres://db")
    db = MagicMock()
    repo_service = MagicMock()
    repo_service.ensure.return_value = "repo-id-123"

    monkeypatch.setattr("ingestion.main.DatabaseManager", MagicMock(return_value=db))
    monkeypatch.setattr("ingestion.main.RepositoryService", MagicMock(return_value=repo_service))

    result = _ensure_repository_record(
        settings=settings,
        github_repo_id=123,
        repo_url="https://github.com/o/r",
        full_name="o/r",
    )

    assert result == "repo-id-123"
    db.connect.assert_called_once_with()
    repo_service.ensure.assert_called_once_with(123, "https://github.com/o/r", "o/r")
    db.close.assert_called_once_with()
