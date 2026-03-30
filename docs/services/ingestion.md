# Ingestion Service

The ingestion service indexes GitHub repositories so their code can be searched semantically. It clones repos, splits code into chunks, generates vector embeddings, and stores everything in PostgreSQL and Milvus. It also generates automated wiki documentation for indexed repositories using an LLM.

## Table of Contents

- [Architecture](#architecture)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Processing Pipelines](#processing-pipelines)
  - [Full Branch Indexing](#full-branch-indexing)
  - [Incremental Indexing](#incremental-indexing)
  - [Wiki Generation](#wiki-generation)
- [Data Models](#data-models)
- [External Dependencies](#external-dependencies)

---

## Architecture

```
HTTP Clients / GitHub Webhooks
         │
         ▼
  ┌─────────────┐
  │  FastAPI     │   POST /index, POST /webhook, GET /status, ...
  │  (main.py)   │
  └──────┬──────┘
         │  starts / signals workflows
         ▼
  ┌─────────────────────────────────────────────┐
  │              Temporal Server                │
  │                                             │
  │  IndexBranchWorkflow                        │
  │  IncrementalIndexWorkflow  (push coalescing)│
  │  GenerateWikiWorkflow                       │
  └──────┬──────────────────────────────────────┘
         │  executes activities
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  Temporal Activities                                         │
  │                                                              │
  │  git         clone/fetch repos, diff commits                 │
  │  chunking    split files into semantic chunks (AST/sliding)  │
  │  embedding   generate vectors via OpenAI or Bedrock          │
  │  storage     write/publish chunks to Postgres + Milvus       │
  │  wiki        generate wiki pages via LLM + RAG               │
  └──────┬───────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │  External Services                           │
  │                                              │
  │  PostgreSQL   metadata, chunks, wiki pages   │
  │  Milvus       vector search                  │
  │  GitHub       repo access (HTTPS + token)    │
  │  OpenAI       embeddings + LLM (optional)    │
  │  AWS Bedrock  embeddings + LLM (optional)    │
  └──────────────────────────────────────────────┘
```

### Key Components

| Component | Location | Role |
|-----------|----------|------|
| FastAPI server | `src/ingestion/main.py` | REST API, auth, workflow dispatch |
| `IndexBranchWorkflow` | `temporal/workflows/index_branch.py` | Full branch indexing |
| `IncrementalIndexWorkflow` | `temporal/workflows/incremental.py` | Push-triggered incremental indexing |
| `GenerateWikiWorkflow` | `temporal/workflows/generate_wiki.py` | Automated wiki generation |
| Chunking strategies | `src/ingestion/chunking/` | `ASTCodeChunker`, `SlidingWindowChunker` |
| Embedding registry | `src/ingestion/embedding/registry.py` | OpenAI / Bedrock embedder selection |
| LLM registry | `src/ingestion/llm/registry.py` | OpenAI / Bedrock LLM selection |
| Service layer | `src/ingestion/services/` | `RepositoryService`, `BranchService`, `ChunkService`, `WikiService` |
| Config | `src/ingestion/utilities/config.py` | `IngestionSettings` (Pydantic) |

---

## API Endpoints

All endpoints except `/health` require authentication. Endpoints that accept an `X-Internal-Token` header validate against `INTERNAL_SERVICE_TOKEN`. The webhook endpoint validates the GitHub HMAC-SHA256 signature via `X-Hub-Signature-256`.

### `POST /index`

Trigger full indexing for one or more repository branches.

**Auth:** `X-Internal-Token` header

**Request body:**
```json
{
  "repositories": [
    {
      "github_repo_id": 123456,
      "repo_url": "https://github.com/owner/repo",
      "full_name": "owner/repo",
      "branches": ["main", "develop"],
      "github_token": "ghp_...",
      "chunker_strategy": "ast_code"
    }
  ]
}
```

**Response:**
```json
{
  "workflow_ids": ["index-branch-123456-main", "index-branch-123456-develop"]
}
```

One `IndexBranchWorkflow` is started per branch. If a workflow for that branch is already running, its handle is returned without starting a duplicate.

---

### `POST /webhook`

Handle GitHub push events to trigger incremental re-indexing.

**Auth:** HMAC-SHA256 via `X-Hub-Signature-256` header (disabled when `GITHUB_WEBHOOK_SECRET` is empty)

**Headers required:** `X-GitHub-Event: push`

**Request body:** Standard GitHub push event payload

**Response:**
```json
{
  "status": "accepted",
  "workflow_id": "incremental-index-123456-main"
}
```

If an `IncrementalIndexWorkflow` for this repo+branch is already running, the new push is **signalled** to the running workflow (push coalescing) rather than starting a new one.

---

### `GET /status/{github_repo_id}`

Return the indexing status for all branches of a repository.

**Auth:** `X-Internal-Token` header

**Response:**
```json
{
  "github_repo_id": 123456,
  "branches": [
    {
      "name": "main",
      "status": "indexed",
      "last_commit": "abc123",
      "indexed_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

Branch `status` values: `indexing`, `indexed`, `failed`.

---

### `POST /generate-wiki`

Trigger wiki generation for an already-indexed repository branch.

**Auth:** `X-Internal-Token` header

**Request body:**
```json
{
  "github_repo_id": 123456,
  "branch": "main"
}
```

**Response:**
```json
{
  "workflow_id": "generate-wiki-123456-main"
}
```

Returns `400` if LLM or embedding strategy is not configured.

---

### `GET /wiki-status/{github_repo_id}`

Return the latest wiki generation status for a repository branch.

**Auth:** `X-Internal-Token` header

**Query params:** `branch` (default: `main`)

**Response:**
```json
{
  "github_repo_id": 123456,
  "branch": "main",
  "status": "completed",
  "wiki_title": "My Repo Wiki",
  "page_count": 12
}
```

Wiki `status` values: `generating`, `completed`, `failed`.

---

### `GET /health`

Health check.

**Response:** `{"status": "ok"}`

---

## Configuration

Configuration is loaded from environment variables via `IngestionSettings` (`src/ingestion/utilities/config.py`). Copy `.env.example` to `.env` to get started.

If the `INGESTION_SETTINGS_SSM_PARAMETER` environment variable is set, settings are loaded from AWS Systems Manager Parameter Store instead.

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DSN` | `postgresql://lighthouse:lighthouse@localhost:5432/lighthouse` | PostgreSQL connection string |
| `MILVUS_URI` | `http://localhost:19530` | Milvus vector database URI |
| `OPENAI_API_KEY` | _(empty)_ | Required when using OpenAI for embeddings or LLM |
| `CHUNKER_STRATEGY` | `sliding_window` | Code chunking strategy: `ast_code` or `sliding_window` |
| `EMBEDDING_STRATEGY` | `openai` | Embedding provider: `openai` or `bedrock` |
| `EMBEDDING_MODEL` | _(strategy default)_ | Override the embedding model |
| `EMBEDDING_DIMENSION` | `0` | Bedrock only — embedding dimension; auto-detected if `0` |
| `LLM_STRATEGY` | `bedrock` | LLM provider for wiki generation: `openai` or `bedrock` |
| `LLM_MODEL` | _(strategy default)_ | Override the LLM model |
| `LLM_REASONING_EFFORT` | _(empty)_ | OpenAI only — reasoning effort for o1/o3 models |
| `GITHUB_WEBHOOK_SECRET` | _(empty)_ | HMAC secret for webhook signature validation; empty disables validation |
| `INTERNAL_SERVICE_TOKEN` | _(empty)_ | Shared token for service-to-service auth; empty disables auth |
| `TEMPORAL_ADDRESS` | `localhost:7233` | Temporal server address |
| `TEMPORAL_TASK_QUEUE` | `ingestion` | Temporal task queue name |
| `CLONE_BASE_DIR` | `/tmp/lighthouse_repos` | Local directory for cloned repositories |

---

## Processing Pipelines

All processing is orchestrated by Temporal workflows. Workflows are durable — they survive worker restarts and can be monitored in the Temporal UI.

### Full Branch Indexing

**Workflow:** `IndexBranchWorkflow` (`temporal/workflows/index_branch.py`)

Triggered by `POST /index`. Indexes all files in a branch from scratch.

```
1. Mark branch status → "indexing"

2. Clone or fetch repository
   - Uses HTTPS with GitHub token if provided
   - Retry: 3 attempts, 5s backoff

3. Chunk all files → staging table
   - Strategy: AST Code (semantic boundaries) or Sliding Window (fixed size)
   - Language detected per file (60+ extensions supported)
   - Skips: lock files, files > 1 MB, binary files
   - Falls back to Sliding Window if AST parsing fails
   - Output: batch_id, chunk_count

4. Embed chunks in parallel batches
   - Batch size: 64 chunks
   - Provider: OpenAI or Bedrock
   - Retry: 5 attempts, 2s backoff (max 60s)

5. Publish staged chunks to final storage
   - Moves StagingChunk → Chunk table (PostgreSQL)
   - Inserts vectors into Milvus code chunks collection
   - Tracks active file versions in IndexedFile

6. Mark branch status → "indexed"

7. [best-effort] Run GenerateWikiWorkflow as child workflow
   - Failure here does NOT fail the indexing workflow

8. [best-effort] Clean up superseded chunk versions
   - Deletes old vectors from Milvus
   - Removes stale rows from Chunk table

On error at any step → mark branch status "failed", clean up staging
```

---

### Incremental Indexing

**Workflow:** `IncrementalIndexWorkflow` (`temporal/workflows/incremental.py`)

Triggered by `POST /webhook` on GitHub push events. Only re-indexes changed files.

**Push coalescing:** If multiple pushes arrive while a workflow is running, they are queued as signals. The workflow waits up to 15 seconds for additional pushes before processing the latest queued push. Earlier pushes in the queue are discarded, since the latest push supersedes them.

```
[signal loop]
  Wait for enqueue_push signal or 15s idle timeout
  Process latest queued push:

  1. Ensure repository record exists (upsert)

  2. Mark branch status → "indexing" with target_commit

  3. Clone or fetch repository

  4. Get changed files between before_commit and after_commit
     - Returns relative paths of added/modified/deleted files

  5. If no changed files → mark "indexed", skip to next push

  6. Chunk only changed files → staging table
     - Same strategy selection as full indexing
     - file_filter limits chunking to changed paths only

  7. Embed changed chunks in parallel batches (64 per batch)

  8. Publish staged chunks incrementally
     - Updates existing file versions for changed files
     - Returns cleanup targets (superseded versions)

  9. Mark branch status → "indexed" with after_commit

  10. [best-effort] Wiki generation child workflow

  11. [best-effort] Cleanup superseded chunk versions

  On error → mark branch "failed", clean up staging
```

---

### Wiki Generation

**Workflow:** `GenerateWikiWorkflow` (`temporal/workflows/generate_wiki.py`)

Triggered by `POST /generate-wiki` or automatically as a child of the indexing workflows. Requires the branch to already be indexed (chunks must exist in Postgres + Milvus).

```
1. Generate wiki structure
   - Gathers up to 500 file paths and 20 sample chunks from indexed code
   - Calls LLM with a structured schema prompt
   - Output: JSON with title, description, sections, pages (slug, title, description, source_file_hints)
   - Creates WikiGeneration record with status "generating"

2. Flatten page list from nested section structure

3. Generate wiki pages in parallel batches (8 pages per batch)
   For each page:
   a. Embed page description
   b. Vector search in code chunks (top 15 results)
   c. Fetch chunk content from PostgreSQL
   d. Call LLM with page title + description + code context
   e. Store generated Markdown in staging table

4. Embed wiki pages in parallel batches (512 per batch)
   - Embeds generated Markdown content
   - Stores embeddings in staging table

5. Move to final storage
   - StagingWikiPage → WikiPage table (PostgreSQL)
   - Insert wiki page vectors into Milvus wiki collection

6. Mark WikiGeneration status → "completed"

On error → mark WikiGeneration "failed", clean up staging wiki rows
```

---

## Data Models

All database models live in the shared `db` package.

| Table | Purpose |
|-------|---------|
| `Repository` | One row per GitHub repo: `github_repo_id`, `full_name`, `repo_url`, `owner_login` |
| `IndexedBranch` | Branch indexing state: `status`, `last_indexed_commit`, `target_commit`, `indexed_at`, encrypted `github_token` |
| `StagingChunk` | Temporary chunk storage during indexing, keyed by `batch_id`. Includes `embedding` column populated during the embed step. |
| `Chunk` | Final indexed chunks: `repository_id`, `branch`, `file_path`, `start_line`, `end_line`, `content`, `language`, `chunk_hash`, `embedding` (vector) |
| `IndexedFile` | Tracks the active `publish_id` per file. Used to identify superseded versions during cleanup. |
| `WikiGeneration` | One row per wiki generation attempt: `status`, `wiki_title`, `structure_json`, `page_count` |
| `StagingWikiPage` | Temporary wiki page storage during generation, keyed by `batch_id` |
| `WikiPage` | Final wiki pages: `slug`, `title`, `content`, `section_path`, `source_files`, `embedding` (vector) |

**Staging pattern:** Both chunk indexing and wiki generation use a staging → publish pattern. Data is written to staging tables first, then atomically moved to final tables. This allows cleanup on failure without corrupting live data.

**Active versioning:** `IndexedFile` records which `publish_id` is currently active for each file. When a file is re-indexed, the old version is marked inactive and cleaned up asynchronously, preventing stale vectors in Milvus.

---

## External Dependencies

### PostgreSQL
Stores all relational metadata: repositories, branch states, chunks, wiki pages. Connection configured via `POSTGRES_DSN`.

### Milvus
Vector database used for semantic search over code chunks and wiki pages. Two collections:
- Code chunks collection (`MILVUS_COLLECTION_NAME` from shared config)
- Wiki pages collection (`WIKI_MILVUS_COLLECTION_NAME` from shared config)

Connection configured via `MILVUS_URI`.

### GitHub
Repositories are cloned/fetched over HTTPS. If a `github_token` is provided, it is injected into the clone URL as `https://x-access-token:{token}@github.com/...` to access private repositories.

### Temporal
Workflow orchestration for all long-running operations. The API server connects as a Temporal client to start and signal workflows. Workers run activities on the `ingestion` task queue. Connection configured via `TEMPORAL_ADDRESS`.

### OpenAI / AWS Bedrock
Used interchangeably for:
- **Embeddings** — generating vectors for code chunks and wiki pages
- **LLM** — generating wiki structure and page content

Selected via `EMBEDDING_STRATEGY` and `LLM_STRATEGY`. Both strategies can be mixed (e.g., Bedrock embeddings + OpenAI LLM).
