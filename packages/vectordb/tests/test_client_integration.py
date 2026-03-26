import pytest
import uuid
from testing_utils.mock_embedding import MockEmbeddingProvider
from vectordb import MilvusClient

@pytest.mark.integration
class TestMilvusClientIntegration:
    def test_ensure_collection_creates(self, milvus_uri):
        # Use a unique collection name to avoid conflicts
        name = f"test_{uuid.uuid4().hex[:8]}"
        client = MilvusClient(uri=milvus_uri, collection_name=name)
        client.ensure_collection(dimension=8)
        # Verify by ensuring again (idempotent)
        client.ensure_collection(dimension=8)
        client.drop_collection()
        client.close()

    def test_insert_and_search(self, milvus_client):
        embedder = MockEmbeddingProvider(dimension=8)
        records = []
        texts = ["hello world", "foo bar", "test code"]
        embeddings = embedder.embed_batch(texts)
        for i, (text, emb) in enumerate(zip(texts, embeddings)):
            records.append({
                "id": str(uuid.uuid4()),
                "chunk_id": f"chunk-{i}",
                "embedding": emb,
                "repository_id": "repo-1",
                "file_path": f"file{i}.py",
                "branch": "main",
            })
        milvus_client.insert(records)

        # Search with first text's embedding
        results = milvus_client.search(query_embedding=embeddings[0], top_k=3)
        assert len(results) == 3
        # The closest result should be the same text
        assert results[0].chunk_id == "chunk-0"
        assert results[0].score >= 0.99  # cosine similarity with itself

    def test_insert_empty(self, milvus_client):
        milvus_client.insert([])  # should not raise

    def test_search_with_filters(self, milvus_client):
        embedder = MockEmbeddingProvider(dimension=8)
        embs = embedder.embed_batch(["text1", "text2"])
        milvus_client.insert([
            {"id": str(uuid.uuid4()), "chunk_id": "c1", "embedding": embs[0], "repository_id": "r1", "file_path": "f.py", "branch": "main"},
            {"id": str(uuid.uuid4()), "chunk_id": "c2", "embedding": embs[1], "repository_id": "r2", "file_path": "f.py", "branch": "main"},
        ])
        results = milvus_client.search(query_embedding=embs[0], top_k=10, filters={"repository_id": "r1"})
        assert all(r.repository_id == "r1" for r in results)

    def test_delete_by_filter(self, milvus_client):
        embedder = MockEmbeddingProvider(dimension=8)
        embs = embedder.embed_batch(["a", "b"])
        milvus_client.insert([
            {"id": str(uuid.uuid4()), "chunk_id": "d1", "embedding": embs[0], "repository_id": "r1", "file_path": "f.py", "branch": "main"},
            {"id": str(uuid.uuid4()), "chunk_id": "d2", "embedding": embs[1], "repository_id": "r2", "file_path": "f.py", "branch": "main"},
        ])
        milvus_client.delete_by_filter('repository_id == "r1"')
        results = milvus_client.search(query_embedding=embs[0], top_k=10)
        assert all(r.repository_id != "r1" for r in results)
