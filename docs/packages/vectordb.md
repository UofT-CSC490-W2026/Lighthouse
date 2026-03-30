# `vectordb`

Shared Milvus wrapper package for Lighthouse vector storage and retrieval. It defines the collection schema contract used for chunk and wiki embeddings and provides a small client with insert, search, and delete helpers.

## What this package contains

- `CollectionField`: canonical Milvus field names.
- `MilvusSearchResult`: normalized search hit dataclass.
- `MilvusClient`: wrapper around `pymilvus.MilvusClient`.

All are re-exported from `vectordb.__init__`.

## Collection schema contract

`MilvusClient.ensure_collection()` creates a collection with these fields:

- `id`: primary key
- `chunk_id`
- `embedding`
- `repository_id`
- `file_path`
- `branch`
- `publish_id`

Index configuration:

- vector field: `embedding`
- index type: `HNSW`
- metric: `COSINE`
- params: `M=16`, `efConstruction=256`

### Schema validation

If the collection already exists, `ensure_collection()` does not silently trust it. It validates that all required fields are present and raises `RuntimeError` if any are missing. This protects the services from reading or writing against an older schema.

## MilvusClient

### Construction

```python
from vectordb import MilvusClient

client = MilvusClient(
    uri="http://localhost:19530",
    collection_name="chunk_embeddings",
)
```

Constructor defaults:

- `uri="http://localhost:19530"`
- `collection_name="embeddings"`

### Ensuring a collection

```python
client.ensure_collection(dimension=3072)
```

The dimension must match the embedding provider used by the caller.

## Insert API

`insert(records)` performs a batch insert and no-ops on `[]`.

Expected record shape:

```python
{
    "id": "...",
    "chunk_id": "...",
    "embedding": [...],
    "repository_id": "...",
    "file_path": "path/to/file.py",
    "branch": "main",
    "publish_id": "legacy",
}
```

The package does not build these records for you; services assemble them from DB rows and embedding outputs.

## Search API

`search(query_embedding, top_k=10, filters=None)` runs vector similarity search and returns `list[MilvusSearchResult]`.

Returned fields:

- `chunk_id`
- `score`
- `repository_id`
- `file_path`
- `branch`
- `publish_id`

### Example

```python
results = client.search(
    query_embedding=query_vector,
    top_k=10,
    filters={"repository_id": "repo-123", "branch": "main"},
)
```

## Filter syntax

The wrapper converts a Python dict into a Milvus boolean filter expression.

### Simple equality

```python
{"repository_id": "repo-123"}
```

becomes:

```python
repository_id == "repo-123"
```

### Supported operators

- `eq` or `==`
- `ne` or `!=`
- `gt` or `>`
- `lt` or `<`
- `gte` or `>=`
- `lte` or `<=`
- `in`
- `like`

### Multi-operator example

```python
{"score": {"gte": 1, "lte": 3}, "branch": "main"}
```

becomes:

```python
(score >= 1 and score <= 3) and branch == "main"
```

### Type rules

- strings are quoted and escaped
- booleans are converted to `true` / `false`
- numbers are emitted directly
- unsupported value types raise `TypeError`
- unsupported operators raise `ValueError`

## Delete and lifecycle APIs

- `delete_by_filter(filter_expr)`: delete matching vectors by a raw Milvus filter expression
- `drop_collection()`: drop the whole collection
- `close()`: close the underlying client

Example:

```python
client.delete_by_filter('repository_id == "repo-123" and branch == "main"')
client.close()
```

## How Lighthouse uses it

- `services/ingestion` creates and ensures the main code and wiki collections before embedding publish steps.
- `services/search` opens clients for both code and wiki retrieval collections.
- The shared collection names come from `shared.config.MILVUS_COLLECTION_NAME` and `shared.config.WIKI_MILVUS_COLLECTION_NAME`.

## Operational assumptions

- Milvus is reachable at the configured URI.
- The embedding dimension passed to `ensure_collection()` matches the active embedding model.
- Existing collections must satisfy the required schema, especially the `publish_id` field introduced in the current contract.
