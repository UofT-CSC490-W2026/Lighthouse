import time
import uuid

import pytest
from testing_utils.mock_embedding import MockEmbeddingProvider
from vectordb import MilvusClient


def _flush(client: MilvusClient) -> None:
    """Flush and wait for Milvus to make inserted data searchable."""
    client._client.flush(client.collection_name)
    time.sleep(0.5)


@pytest.mark.integration
class TestMilvusClientIntegration:
    def test_ensure_collection_creates(self, milvus_uri):
        name = f"test_{uuid.uuid4().hex[:8]}"
        client = MilvusClient(uri=milvus_uri, collection_name=name)
        client.ensure_collection(dimension=8)
        client.ensure_collection(dimension=8)  # idempotent
        client.drop_collection()
        client.close()

    def test_insert_and_search(self, milvus_client):
        embedder = MockEmbeddingProvider(dimension=8)
        texts = ["hello world", "foo bar", "test code"]
        embeddings = embedder.embed_batch(texts)
        records = [
            {
                "id": str(uuid.uuid4()),
                "chunk_id": f"chunk-{i}",
                "embedding": emb,
                "repository_id": "repo-1",
                "file_path": f"file{i}.py",
                "branch": "main",
            }
            for i, emb in enumerate(embeddings)
        ]
        milvus_client.insert(records)
        _flush(milvus_client)

        results = milvus_client.search(query_embedding=embeddings[0], top_k=3)
        assert len(results) == 3
        assert results[0].chunk_id == "chunk-0"

    def test_insert_empty(self, milvus_client):
        milvus_client.insert([])

    def test_search_with_filters(self, milvus_client):
        embedder = MockEmbeddingProvider(dimension=8)
        embs = embedder.embed_batch(["text1", "text2"])
        milvus_client.insert([
            {"id": str(uuid.uuid4()), "chunk_id": "c1", "embedding": embs[0],
             "repository_id": "r1", "file_path": "f.py", "branch": "main"},
            {"id": str(uuid.uuid4()), "chunk_id": "c2", "embedding": embs[1],
             "repository_id": "r2", "file_path": "f.py", "branch": "main"},
        ])
        _flush(milvus_client)

        results = milvus_client.search(
            query_embedding=embs[0], top_k=10, filters={"repository_id": "r1"}
        )
        assert len(results) >= 1
        assert all(r.repository_id == "r1" for r in results)

    def test_delete_by_filter(self, milvus_client):
        embedder = MockEmbeddingProvider(dimension=8)
        embs = embedder.embed_batch(["a", "b"])
        milvus_client.insert([
            {"id": str(uuid.uuid4()), "chunk_id": "d1", "embedding": embs[0],
             "repository_id": "r1", "file_path": "f.py", "branch": "main"},
            {"id": str(uuid.uuid4()), "chunk_id": "d2", "embedding": embs[1],
             "repository_id": "r2", "file_path": "f.py", "branch": "main"},
        ])
        _flush(milvus_client)

        milvus_client.delete_by_filter('repository_id == "r1"')
        _flush(milvus_client)

        results = milvus_client.search(query_embedding=embs[0], top_k=10)
        assert all(r.repository_id != "r1" for r in results)
