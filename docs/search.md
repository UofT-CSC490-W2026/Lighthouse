# Search Service

## Purpose

The search service is Lighthouse's retrieval backend.

Its main job is to turn a coding-oriented query into ranked code snippets that can
be returned to the MCP service and, from there, to coding agents or the web UI.
The intended focus is repository-aware code retrieval for tasks such as:

- finding relevant implementations for a task description
- surfacing related files or code regions across a repository
- retrieving snippets that help explain architecture or behavior
- narrowing context before an agent makes a code change

Today, the primary entrypoint is `POST /search`. The service combines vector
search and PostgreSQL full-text search into one ranked result set. The endpoint
currently accepts a list of typed search requests and supports the `hybrid`
search method.

## Current State

The service is currently built around:

- a FastAPI app with a lifespan-based dependency setup
- a strategy registry with `hybrid` as the only implemented search method today
- PostgreSQL as the source of chunk content and repository metadata
- Milvus as the vector index
- a configurable embedding provider for query embedding generation
  with Bedrock as the default and OpenAI as an optional override
- shared typed request and response schemas in `packages/shared`

Important current limitations:

- `file_path` is accepted on the request schema but is not currently used by the
  search strategy
- snippet `reason` fields are defined in the schema but are not populated by the
  current strategy
- keyword search is hard-coded to PostgreSQL English full-text search

## Source Layout

The current search service package lives under `services/search/src/search`:

```text
services/search/src/search/
  main.py
  config.py
  strategies/
    __init__.py
    search_strategy.py
    hybrid_strategy.py
    example_strategy.py
```

Related shared packages:

- `packages/shared/src/shared/schemas/search.py`: typed request and response contracts
- `packages/db/src/db/models/indexing.py`: `Chunk` storage model used for retrieval
- `packages/embedding/src/embedding/`: embedding provider abstraction plus
  Bedrock and OpenAI implementations

## Architecture

### App Lifespan

`services/search/src/search/main.py` creates the FastAPI app and wires service
dependencies during lifespan startup.

At startup it:

1. loads typed settings
2. connects a `DatabaseManager`
3. creates a `MilvusClient`
4. creates the configured embedding provider
5. registers the available search strategies on `app.state.registry`

At shutdown it:

1. closes the Milvus client
2. closes the database manager

### Search Strategy

`services/search/src/search/strategies/hybrid_strategy.py` contains the current
retrieval logic, and `services/search/src/search/registry.py` dispatches typed
requests to the registered strategy implementations.

`HybridSearchStrategy` receives:

- `db_manager`
- `milvus`
- `embedder`

Its `search()` method performs one end-to-end retrieval pipeline for each request.

### Request Flow

The request flow is:

1. resolve the Lighthouse repository row from `github_repo_id`
2. build optional Milvus filters from the resolved repository ID and branch
3. generate a query embedding
4. run vector similarity search in Milvus
5. run PostgreSQL full-text search on chunk content
6. fuse both ranked result sets with reciprocal rank fusion
7. fetch the full chunk rows from PostgreSQL
8. serialize ordered snippets into the shared `SearchResult` schema

If vector search fails, the service logs the error and falls back to keyword-only
search instead of failing the whole request.

## Search and Retrieval Model

The request and response types live in `packages/shared/src/shared/schemas/search.py`.

### `SearchRequest`

`SearchRequest` is a discriminated union. The current concrete request type is
`HybridRequest`, and `POST /search` accepts a list of these request envelopes.

Current `HybridRequest` fields:

- `method`
- `query`
- `github_repo_id`
- `branch`
- `file_path`
- `top_k`

Current behavior notes:

- `branch` defaults to `"main"`
- `top_k` is bounded from `1` to `100`
- `file_path` is accepted by the schema but is not yet applied as a filter in
  `HybridSearchStrategy`

### `CodeSnippet`

Returned snippets include:

- `file_path`
- `start_line`
- `end_line`
- `content`
- `language`
- `score`
- `reason`

Current behavior notes:

- `score` is populated from the fused ranking score
- `reason` is defined but currently returned as `None`

### `SearchResult`

The top-level response contains:

- `snippets`
- `query`
- `total_results`

## Hybrid Retrieval Pipeline

The current strategy combines two retrieval methods.

### Vector Search

Vector retrieval uses:

- query embedding generation through the configured embedding provider
- Milvus search against the shared collection name
- optional filters for `repository_id` and `branch`

The strategy currently asks Milvus for `top_k * 2` hits before fusion.

### Keyword Search

Keyword retrieval uses raw SQL against PostgreSQL `chunks`.

The current SQL:

- builds a `tsvector` from `content`
- uses `plainto_tsquery('english', ...)`
- ranks results with `ts_rank`
- optionally filters by repository and branch
- returns up to `top_k * 2` rows

### Reciprocal Rank Fusion

`HybridSearchStrategy._rrf_fusion()` combines vector and keyword rankings into one
fused score per chunk ID.

The fused result set is then:

- sorted descending by fused score
- truncated to `top_k`
- expanded back into full snippets by loading the `Chunk` rows from PostgreSQL

## Current HTTP Surface

The current HTTP routes are:

- `POST /search`
- `GET /search/methods`
- `GET /health`

`POST /search` accepts a list of typed search requests and returns a `SearchResult`.

## Data Dependencies

The search service depends on:

- `repositories` for mapping `github_repo_id` to the internal repository row
- `chunks` for stored code content and snippet metadata
- the Milvus collection configured by `MILVUS_COLLECTION_NAME`

The `Chunk` model includes:

- repository reference
- branch
- file path
- line range
- content
- language
- chunk hash

Search returns chunk content from PostgreSQL, not directly from Milvus.

## Configuration

The search service uses a typed settings model in
`services/search/src/search/config.py`.

### Load Order

Settings are loaded through the shared SSM-aware settings helper using:

1. explicit init values
2. environment variables
3. `.env` values
4. file secret settings
5. SSM parameter payload

### SSM Support

If `SEARCH_SETTINGS_SSM_PARAMETER` is set, the service attempts to load one JSON
object from AWS Systems Manager Parameter Store and use it as a settings source.

### Important Settings

- `postgres_dsn`
- `milvus_uri`
- `embedding_strategy`
- `embedding_model`
- `embedding_dimension`
- `openai_api_key` when `EMBEDDING_STRATEGY=openai`

## Error Model and Runtime Behavior

The search service currently keeps its external error model simple:

- FastAPI and Pydantic handle request validation errors
- unhandled retrieval errors propagate as normal server failures
- vector-search-specific failures are caught and logged, then downgraded to
  keyword-only retrieval

This means the service prefers degraded retrieval over hard failure when only the
vector backend is unavailable.

## Local Development

The search service Docker image runs:

```shell
uvicorn search.main:app --host 0.0.0.0 --port 8002
```

The service expects working access to:

- PostgreSQL
- Milvus
- embedding backend credentials:
  AWS credentials for the default Bedrock path, or an OpenAI API key when
  `EMBEDDING_STRATEGY=openai`

## Current Limitations and Follow-Up Work

The most important gaps at the time of writing are:

- `file_path` is not yet part of the actual retrieval filtering logic
- snippet `reason` values are not generated
- keyword search assumes English tokenization for all code and comments
- there is no reranking pass beyond reciprocal rank fusion
- there is no explicit auth layer at the service boundary
- retrieval quality depends on ingestion having already populated both PostgreSQL
  chunks and the Milvus collection
- changing embedding strategy or embedding dimension requires re-indexing so the
  Milvus collection matches the active vector shape

## Design Principles for Future Work

When extending this service, keep these constraints in place:

- request and response contracts should stay typed and shared
- retrieval should remain repository-aware and branch-aware
- degraded operation is preferable to total failure when one backend is down
- PostgreSQL should remain the source of truth for returned snippet content
- runtime docs should describe implemented retrieval behavior, not intended future ranking ideas
