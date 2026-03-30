# Search Service

The search service is a FastAPI microservice that provides hybrid search over indexed code and wiki content. It combines vector similarity search with PostgreSQL full-text search (FTS), fused via Reciprocal Rank Fusion (RRF).

## Table of Contents

- [Architecture](#architecture)
- [Configuration](#configuration)
- [API](#api)
- [Search Strategies](#search-strategies)
- [Algorithms](#algorithms)
- [Authentication](#authentication)
- [Running Locally](#running-locally)

---

## Architecture

```
services/search/
├── src/search/
│   ├── main.py                      # FastAPI app, endpoints, lifespan
│   ├── config.py                    # SearchSettings (Pydantic BaseSettings)
│   ├── strategies/
│   │   ├── search_strategy.py       # Abstract base class
│   │   ├── hybrid_strategy.py       # Vector + FTS for code
│   │   ├── wiki_search_strategy.py  # Vector + FTS for wiki
│   │   └── llm_combined_strategy.py # LLM keywords + multi-domain RRF + reranking
│   └── reranker/
│       ├── base_reranker.py         # Abstract base class
│       └── cohere_reranker.py       # Cohere async reranker
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── profiles/                        # Performance profiling utilities
├── Dockerfile
└── pyproject.toml
```

**External dependencies:**
- **PostgreSQL** — stores `chunks`, `indexed_files`, `wiki_pages`, and `repositories`
- **Milvus** — stores vector embeddings for code (one collection) and wiki (separate collection)
- **OpenAI** — embeddings and LLM keyword generation
- **Cohere** — reranking

---

## Configuration

`SearchSettings` (in `config.py`) loads from environment variables or a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_DSN` | `postgresql://lighthouse:lighthouse@localhost:5432/lighthouse` | PostgreSQL connection string |
| `MILVUS_URI` | `http://localhost:19530` | Milvus vector DB URI |
| `EMBEDDING_STRATEGY` | `openai` | Embedding provider (`openai`, `bedrock`) |
| `EMBEDDING_MODEL` | _(provider default)_ | Embedding model name |
| `OPENAI_API_KEY` | — | OpenAI API key (embeddings + LLM) |
| `COHERE_API_KEY` | — | Cohere API key (reranking) |
| `INTERNAL_SERVICE_TOKEN` | — | Shared secret for service-to-service auth |
| `RERANK_MODEL` | `rerank-v4.0-pro` | Cohere rerank model |
| `LLM_MODEL` | `gpt-4.1-nano` | LLM for keyword generation |
| `LLM_REASONING_EFFORT` | `none` | LLM extended thinking effort |

---

## API

The service runs on port **8002**.

### `POST /search`

Hybrid search over code and/or wiki content.

**Request body:**

```json
{
  "query": "authentication middleware",
  "github_repo_id": 123,
  "branch": "main",
  "top_k": 10,
  "context_source": "code",
  "context_sources": null
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `query` | `string` | required | Search query |
| `github_repo_id` | `int` | required | GitHub repository ID |
| `branch` | `string` | `"main"` | Git branch to search |
| `top_k` | `int` | `10` | Number of results (1–100) |
| `context_source` | `"code" \| "wiki" \| "llm_combined"` | `"code"` | Single source (used if `context_sources` is null) |
| `context_sources` | `array` | `null` | Override; search multiple sources |

**Response** depends on which sources are requested:

- Single `code` → `SearchResult` with `CodeSnippet[]`
- Single `wiki` → `WikiSearchResult` with `WikiSnippet[]`
- Multiple sources or `llm_combined` → `CombinedSearchResult` with `CombinedSnippet[]`

**`CodeSnippet`:**

```json
{
  "file_path": "src/auth/middleware.py",
  "start_line": 42,
  "end_line": 67,
  "content": "...",
  "language": "python",
  "score": 0.034,
  "reason": null
}
```

**`WikiSnippet`:**

```json
{
  "page_title": "Authentication",
  "slug": "authentication",
  "section_path": "Middleware",
  "content_snippet": "...",
  "score": 0.021
}
```

**`CombinedSnippet`:**

```json
{
  "context_source": "code",
  "content": "...",
  "score": 0.041,
  "file_path": "src/auth/middleware.py",
  "start_line": 42,
  "end_line": 67,
  "reason": null,
  "page_title": null,
  "slug": null,
  "section_path": null
}
```

**Error — branch not indexed (404):**

```json
{
  "code": "BRANCH_UNAVAILABLE",
  "message": "Branch requested not indexed or does not exist: \"dev\"",
  "recoverable": true,
  "context": {
    "requested_branch": "dev",
    "indexed_branches": ["main", "develop"]
  }
}
```

---

### `POST /search/wiki`

Convenience endpoint for wiki-only search. Accepts the same body as `/search` and returns `WikiSearchResult`.

---

### `GET /health`

```json
{"status": "ok"}
```

Does not require authentication.

---

## Search Strategies

### HybridSearchStrategy (code)

Defined in `strategies/hybrid_strategy.py`. Used when `context_source = "code"`.

**Steps:**

1. Resolve `github_repo_id` → internal `repo.id`
2. Check that the requested branch has indexed data; raise `BranchNotIndexedError` otherwise
3. Embed the query and run vector search on Milvus (fetches `top_k × 4`, capped at 200)
4. Filter vector results by active publish ID (see [Publish Filtering](#publish-filtering))
5. Run PostgreSQL FTS on `chunks.content`
6. RRF-fuse both ranked lists
7. Load chunk objects from DB and return `top_k` `CodeSnippet`s

---

### HybridWikiSearchStrategy (wiki)

Defined in `strategies/wiki_search_strategy.py`. Used when `context_source = "wiki"`.

Same pipeline as the code strategy but queries `wiki_pages` instead of `chunks`. No publish filtering is applied to wiki results.

---

### LLMCombinedSearchStrategy (llm_combined / multi-source)

Defined in `strategies/llm_combined_strategy.py`. Used when `context_sources` contains multiple values or `context_source = "llm_combined"`.

**Multi-phase pipeline:**

```
Phase 1 (parallel)
  ├── LLM: extract 3–5 keywords from the query
  ├── Vector search: code embeddings
  └── Vector search: wiki embeddings

Phase 2 (parallel keyword searches)
  ├── Code FTS (original query)
  ├── Code FTS (LLM keywords)
  ├── Wiki FTS (original query)
  └── Wiki FTS (LLM keywords)

Phase 3: RRF within each domain (code, wiki), then cross-domain RRF

Phase 4: Cohere reranking on top candidates → return top_k
```

Falls back gracefully if LLM keyword generation or reranking fails.

---

## Algorithms

### Reciprocal Rank Fusion (RRF)

Combines multiple ranked lists into a single ranking:

```
score(item) = Σ  1 / (k + rank + 1)
              lists where item appears
```

- `k = 60` by default (dampens the contribution of lower-ranked items)
- Items appearing in multiple lists accumulate scores from each
- Final list is sorted descending by score

`_rrf_fusion_multi()` in `llm_combined_strategy.py` generalizes this to N input lists.

### Publish Filtering

Code chunks are versioned via `publish_id`. After each ingestion run a new `publish_id` is written to `IndexedFile.active_publish_id`. The filter logic:

- If a file has an `active_publish_id`: keep only chunks whose `publish_id` matches
- If a file has no `active_publish_id`: keep only chunks with `publish_id = "legacy"`

This prevents stale chunks from surfacing in results after a re-index. The filter runs as a batch DB lookup after the vector search step.

---

## Authentication

All endpoints except `/health` require an `Authorization` header validated by `shared.auth.verify_internal_token`. Set the `INTERNAL_SERVICE_TOKEN` environment variable and pass it as:

```
Authorization: Bearer <token>
```

---

## Running Locally

**Prerequisites:** PostgreSQL and Milvus running locally (see top-level `docker-compose.yml`).

```bash
cd services/search

cp .env.example .env
# Fill in OPENAI_API_KEY, COHERE_API_KEY, INTERNAL_SERVICE_TOKEN

uv run fastapi dev src/search/main.py
```

Service starts at `http://localhost:8000` (dev mode) or `http://0.0.0.0:8002` (production).

**Running tests:**

```bash
# Unit tests only
uv run pytest tests/unit -m unit

# Integration tests (requires real DB + Milvus)
uv run pytest tests/integration -m integration

# E2E tests (requires running service)
uv run pytest tests/e2e -m e2e
```

**Docker:**

```bash
docker build -t search-service .
docker run -p 8002:8002 \
  -e POSTGRES_DSN="postgresql://..." \
  -e MILVUS_URI="http://..." \
  -e OPENAI_API_KEY="sk-..." \
  -e COHERE_API_KEY="..." \
  -e INTERNAL_SERVICE_TOKEN="..." \
  search-service
```
