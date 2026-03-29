import uuid

import pytest
import httpx
from httpx import ASGITransport

from db import Chunk
from shared.config import MILVUS_COLLECTION_NAME, WIKI_MILVUS_COLLECTION_NAME
from search.config import SearchSettings
from testing_utils.mock_embedding import MockEmbeddingProvider
from testing_utils.factories import (
    create_repository,
    create_wiki_generation,
    create_wiki_page,
)
from vectordb import MilvusClient


TEST_EMBEDDING_DIMENSION = 8


@pytest.fixture
def search_settings(pg_dsn, milvus_uri):
    return SearchSettings(
        postgres_dsn=pg_dsn,
        milvus_uri=milvus_uri,
        openai_api_key="test",
    )


@pytest.fixture
def e2e_milvus_client(milvus_uri):
    """Milvus client using the same collection name as the search service."""
    client = MilvusClient(uri=milvus_uri, collection_name=MILVUS_COLLECTION_NAME)
    client.ensure_collection(dimension=TEST_EMBEDDING_DIMENSION)
    yield client
    client.drop_collection()
    client.close()


@pytest.fixture
def e2e_wiki_milvus_client(milvus_uri):
    """Milvus client using the wiki collection name."""
    client = MilvusClient(uri=milvus_uri, collection_name=WIKI_MILVUS_COLLECTION_NAME)
    client.ensure_collection(dimension=TEST_EMBEDDING_DIMENSION)
    yield client
    client.drop_collection()
    client.close()


@pytest.fixture
async def client(
    search_settings,
    mock_embedder,
    db_manager,
    e2e_milvus_client,
    e2e_wiki_milvus_client,
):
    """Create an ASGI test client for the search service.

    httpx's ASGITransport does not invoke ASGI lifespan events, so we import
    the module-level ``app`` and set ``app.state.strategy`` directly.
    """
    from search.main import app
    from search.strategies.hybrid_strategy import HybridSearchStrategy
    from search.strategies.wiki_search_strategy import HybridWikiSearchStrategy

    app.state.settings = search_settings
    app.state.strategy = HybridSearchStrategy(
        db_manager=db_manager,
        milvus=e2e_milvus_client,
        embedder=mock_embedder,
    )
    app.state.wiki_strategy = HybridWikiSearchStrategy(
        db_manager=db_manager,
        milvus=e2e_wiki_milvus_client,
        embedder=mock_embedder,
    )

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.e2e
class TestSearchEndpoints:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_search_success(self, client, db_manager, e2e_milvus_client, mock_embedder):
        repo = create_repository(db_manager)

        # Seed data: two chunks with distinct content
        texts = ["python sorting algorithm", "react component lifecycle"]
        embeddings = mock_embedder.embed_batch(texts)

        with db_manager.connection_context():
            for i, (text, emb) in enumerate(zip(texts, embeddings)):
                cid = str(uuid.uuid4())
                Chunk.create(
                    id=cid,
                    repository=repo,
                    branch="main",
                    file_path=f"f{i}.py",
                    start_line=1,
                    end_line=10,
                    content=text,
                    language="python",
                    chunk_hash=uuid.uuid4().hex,
                )
                e2e_milvus_client.insert([{
                    "id": cid,
                    "chunk_id": cid,
                    "embedding": emb,
                    "repository_id": repo.id,
                    "file_path": f"f{i}.py",
                    "branch": "main",
                    "publish_id": "legacy",
                }])

        resp = await client.post("/search", json={
            "query": "python sorting algorithm",
            "github_repo_id": repo.github_repo_id,
            "branch": "main",
            "top_k": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "snippets" in data
        assert data["query"] == "python sorting algorithm"

    @pytest.mark.asyncio
    async def test_search_invalid_request(self, client):
        resp = await client.post("/search", json={
            "query": "test",
            "github_repo_id": 999,
            "top_k": 0,  # invalid: ge=1
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_no_results(self, client, db_manager):
        repo = create_repository(db_manager)

        resp = await client.post("/search", json={
            "query": "nonexistent content",
            "github_repo_id": repo.github_repo_id,
            "branch": "main",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["snippets"] == []

    @pytest.mark.asyncio
    async def test_search_returns_matching_snippet_first(
        self, client, db_manager, e2e_milvus_client, mock_embedder
    ):
        """The snippet whose text matches the query should rank highest."""
        repo = create_repository(db_manager)

        target_text = "binary search tree implementation"
        distractor_text = "http server request handler"
        texts = [target_text, distractor_text]
        embeddings = mock_embedder.embed_batch(texts)

        with db_manager.connection_context():
            for i, (text, emb) in enumerate(zip(texts, embeddings)):
                cid = str(uuid.uuid4())
                Chunk.create(
                    id=cid,
                    repository=repo,
                    branch="main",
                    file_path=f"search_{i}.py",
                    start_line=1,
                    end_line=10,
                    content=text,
                    language="python",
                    chunk_hash=uuid.uuid4().hex,
                )
                e2e_milvus_client.insert([{
                    "id": cid,
                    "chunk_id": cid,
                    "embedding": emb,
                    "repository_id": repo.id,
                    "file_path": f"search_{i}.py",
                    "branch": "main",
                    "publish_id": "legacy",
                }])

        resp = await client.post("/search", json={
            "query": target_text,
            "github_repo_id": repo.github_repo_id,
            "branch": "main",
            "top_k": 5,
        })
        assert resp.status_code == 200
        snippets = resp.json()["snippets"]
        assert len(snippets) >= 1
        assert snippets[0]["content"] == target_text

    @pytest.mark.asyncio
    async def test_search_respects_top_k(
        self, client, db_manager, e2e_milvus_client, mock_embedder
    ):
        """The number of returned snippets should not exceed top_k."""
        repo = create_repository(db_manager)

        texts = [f"algorithm variant {i}" for i in range(5)]
        embeddings = mock_embedder.embed_batch(texts)

        with db_manager.connection_context():
            for i, (text, emb) in enumerate(zip(texts, embeddings)):
                cid = str(uuid.uuid4())
                Chunk.create(
                    id=cid,
                    repository=repo,
                    branch="main",
                    file_path=f"algo_{i}.py",
                    start_line=1,
                    end_line=10,
                    content=text,
                    language="python",
                    chunk_hash=uuid.uuid4().hex,
                )
                e2e_milvus_client.insert([{
                    "id": cid,
                    "chunk_id": cid,
                    "embedding": emb,
                    "repository_id": repo.id,
                    "file_path": f"algo_{i}.py",
                    "branch": "main",
                    "publish_id": "legacy",
                }])

        resp = await client.post("/search", json={
            "query": "algorithm variant",
            "github_repo_id": repo.github_repo_id,
            "branch": "main",
            "top_k": 2,
        })
        assert resp.status_code == 200
        snippets = resp.json()["snippets"]
        assert len(snippets) <= 2

    @pytest.mark.asyncio
    async def test_search_combines_code_and_wiki_results(
        self,
        client,
        db_manager,
        e2e_milvus_client,
        e2e_wiki_milvus_client,
        mock_embedder,
    ):
        repo = create_repository(db_manager)
        wiki_generation = create_wiki_generation(
            db_manager,
            repo,
            branch="main",
            status="completed",
        )
        wiki_page = create_wiki_page(
            db_manager,
            wiki_generation,
            repo,
            branch="main",
            slug="cache-keys",
            title="Cache Keys",
            section_path="reference/cache",
            content="Cache keys are lowercased and versioned.",
        )

        code_text = (
            "def build_cache_key(namespace, identifier, *, version='v1'):\n"
            "    # Cache keys are lowercased and versioned.\n"
            "    return f'{namespace}:{identifier}:{version}'.lower()\n"
        )
        wiki_text = wiki_page.content
        code_embedding, wiki_embedding = mock_embedder.embed_batch([code_text, wiki_text])

        with db_manager.connection_context():
            chunk_id = str(uuid.uuid4())
            Chunk.create(
                id=chunk_id,
                repository=repo,
                branch="main",
                file_path="providerlib/cache.py",
                start_line=1,
                end_line=3,
                content=code_text,
                language="python",
                chunk_hash=uuid.uuid4().hex,
            )
            e2e_milvus_client.insert(
                [
                    {
                        "id": chunk_id,
                        "chunk_id": chunk_id,
                        "embedding": code_embedding,
                        "repository_id": repo.id,
                        "file_path": "providerlib/cache.py",
                        "branch": "main",
                        "publish_id": "legacy",
                    }
                ]
            )
            e2e_wiki_milvus_client.insert(
                [
                    {
                        "id": wiki_page.id,
                        "chunk_id": wiki_page.id,
                        "embedding": wiki_embedding,
                        "repository_id": repo.id,
                        "file_path": wiki_page.slug,
                        "branch": "main",
                        "publish_id": "legacy",
                    }
                ]
            )

        resp = await client.post(
            "/search",
            json={
                "query": "cache keys lowercased versioned",
                "github_repo_id": repo.github_repo_id,
                "branch": "main",
                "top_k": 5,
                "context_sources": ["code", "wiki"],
            },
        )

        assert resp.status_code == 200
        snippets = resp.json()["snippets"]
        assert len(snippets) == 2
        assert {snippet["context_source"] for snippet in snippets} == {"code", "wiki"}
