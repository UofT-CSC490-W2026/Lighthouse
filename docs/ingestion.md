# Ingestion Service

## Purpose

The ingestion service builds and maintains the searchable code index used by the
search service.

Its main job is to take repository metadata or GitHub push events and turn them
into indexed branch state, persisted code chunks, and vector embeddings that can
later be searched for coding context. The intended focus is:

- initial repository indexing
- branch-level indexing status tracking
- incremental re-indexing after GitHub pushes
- preparing both PostgreSQL and Milvus search backends from the same pipeline

Today, the primary entrypoints are `POST /index`, `POST /webhook`, and
`GET /status/{github_repo_id:int}`.

## Current State

The service is currently built around:

- a FastAPI app with typed settings
- a Temporal client used to start indexing workflows
- parent and child workflows for repository and branch indexing
- activity-based steps for git, chunking, embedding, storage, and branch updates
- PostgreSQL tables for repository, branch, final chunk, and staging chunk state
- Milvus storage for vector embeddings

Important current limitations:

- the HTTP endpoints do not currently enforce authentication
- indexing status is represented as unconstrained strings such as `pending`,
  `indexing`, `indexed`, and `failed`
- failure cleanup is best effort and happens only after workflow errors are caught
- webhook-driven incremental indexing assumes the repo can already be cloned or fetched locally

## Source Layout

The current ingestion service package lives under `services/ingestion/src/ingestion`:

```text
services/ingestion/src/ingestion/
  main.py
  utilities/
    config.py
    git_ops.py
    services/
      repository.py
      branch.py
      chunk.py
  chunking/
    base_chunker.py
    sliding_window_chunker.py
    registry.py
  embedding/
    registry.py
  language/
    detector.py
  temporal/
    worker.py
    workflows/
      index_repository.py
      index_branch.py
      incremental.py
    activities/
      repository.py
      branch.py
      git.py
      chunking.py
      embedding.py
      storage.py
      inputs.py
      helpers.py
```

Related shared packages:

- `packages/shared/src/shared/schemas/ingestion.py`: HTTP request and response contracts
- `packages/db/src/db/models/indexing.py`: `IndexedBranch`, `Chunk`, and `StagingChunk`
- `packages/embedding/src/embedding/`: embedding providers used during indexing

## Architecture

### App Lifespan

`services/ingestion/src/ingestion/main.py` creates the FastAPI app and connects a
Temporal client during lifespan startup.

At startup it:

1. loads typed settings
2. stores them on `app.state.settings`
3. connects `temporalio.client.Client`
4. stores the client on `app.state.temporal_client`

The HTTP service itself does not execute indexing work directly. It starts Temporal
workflows and returns accepted responses.

### Workflow Model

The service splits orchestration into:

- `IndexRepositoryWorkflow`: ensure the repository record exists, then fan out one
  child workflow per requested branch
- `IndexBranchWorkflow`: run the full branch indexing pipeline
- `IncrementalIndexWorkflow`: re-index only files changed by a push event

### Activity Model

Activities provide the concrete side-effecting work:

- repository activities ensure shared repository rows exist
- branch activities update branch status records
- git activities clone, fetch, and diff repositories
- chunking activities read files and write staging chunks
- embedding activities generate embeddings in batches
- storage activities delete old data, move staged chunks to final storage, and
  clean staging rows

## Public HTTP Surface

The current HTTP routes are:

- `POST /index`
- `POST /webhook`
- `GET /status/{github_repo_id:int}`
- `GET /health`

### `POST /index`

This endpoint accepts `IndexRequest` and starts one top-level repository workflow
per requested repository.

The response is `IndexAcceptedResponse` with:

- `status = "accepted"`
- `workflow_ids`

Workflow IDs currently use the form:

- `index-<github_repo_id>`

### `POST /webhook`

This endpoint handles GitHub push events for incremental indexing.

Current behavior:

- validates `X-Hub-Signature-256` if `github_webhook_secret` is configured
- ignores non-`push` events
- ignores refs that are not branch pushes
- extracts repository, branch, and commit range data
- starts an `IncrementalIndexWorkflow`

Workflow IDs currently use the form:

- `incremental-<github_repo_id>-<branch>-<after_commit_prefix>`

### `GET /status/{github_repo_id:int}`

This endpoint reads the database directly and returns all known branch status rows
for a repository as `IndexStatusResponse`.

Each branch entry includes:

- `branch_name`
- `status`
- `last_indexed_commit`
- `indexed_at`

## Initial Indexing Flow

Initial indexing begins with `IndexRepositoryWorkflow` in
`services/ingestion/src/ingestion/temporal/workflows/index_repository.py`.

The current flow is:

1. ensure the shared repository row exists
2. start one `IndexBranchWorkflow` child workflow per requested branch
3. wait for all child workflows to finish
4. return a text summary of branch successes and failures

### Branch Indexing Flow

`IndexBranchWorkflow` currently performs:

1. mark the branch as `indexing`
2. clone or fetch the repository and resolve the latest commit
3. chunk the branch contents into the staging table
4. if there are no chunks, mark the branch as `indexed` and stop
5. delete existing chunks for that repository branch
6. embed staged chunks in batches
7. move staged chunks into final PostgreSQL storage and Milvus
8. mark the branch as `indexed`

On failure it:

- marks the branch as `failed`
- cleans up staging rows if a batch was already created
- re-raises the error so Temporal sees the failure

## Incremental Indexing Flow

Incremental indexing is implemented in
`services/ingestion/src/ingestion/temporal/workflows/incremental.py`.

The current flow is:

1. ensure the repository row exists
2. mark the branch as `indexing`
3. clone or fetch the repository
4. compute changed files between `before_commit` and `after_commit`
5. if there are no changed files, mark the branch as `indexed` and stop
6. delete existing chunks only for the changed files
7. rechunk only the changed files into staging
8. if chunks were produced, embed them in batches
9. move staged chunks into final PostgreSQL storage and Milvus
10. mark the branch as `indexed`

On failure it follows the same `failed` status and staging cleanup pattern as the
full branch workflow.

## Chunking and Storage Model

### Chunking

`services/ingestion/src/ingestion/temporal/activities/chunking.py` reads repository
files from disk, detects language from file extension, chunks file content, and
writes staging rows through `ChunkService`.

Current behavior notes:

- unreadable files are skipped with a warning
- empty files are skipped
- when `file_filter` is provided, only those changed files are processed
- chunk rows carry repository ID, branch, file path, line ranges, content,
  language, and chunk hash

### Storage

`services/ingestion/src/ingestion/temporal/activities/storage.py` delegates storage
operations to `ChunkService`.

Current storage operations are:

- delete all chunks for a branch from PostgreSQL and Milvus
- delete chunks for a specific file set from PostgreSQL and Milvus
- move staged chunks to final PostgreSQL storage and Milvus
- clean up staging rows

This means PostgreSQL and Milvus are updated as part of the same indexing pipeline,
with PostgreSQL holding final chunk content and Milvus holding vector search state.

## Data Model

The indexing data models live in `packages/db/src/db/models/indexing.py`.

### `IndexedBranch`

Tracks per-repository, per-branch indexing state with fields including:

- `repository`
- `branch_name`
- `last_indexed_commit`
- `status`
- `github_token_encrypted`
- `indexed_at`
- timestamps

The `(repository, branch_name)` pair is unique.

### `Chunk`

Stores final searchable chunk content with fields including:

- `repository`
- `branch`
- `file_path`
- `start_line`
- `end_line`
- `content`
- `language`
- `chunk_hash`

### `StagingChunk`

Stores temporary chunk rows between workflow steps with fields including:

- `batch_id`
- `seq_index`
- repository and branch identifiers
- file path and line range
- content
- language
- chunk hash
- embedding blob

The staging table exists to separate chunk creation and embedding from final commit
into PostgreSQL and Milvus.

## Configuration

The ingestion service uses a typed settings model in
`services/ingestion/src/ingestion/utilities/config.py`.

### Load Order

Settings are loaded through the shared SSM-aware settings helper using:

1. explicit init values
2. environment variables
3. `.env` values
4. file secret settings
5. SSM parameter payload

### SSM Support

If `INGESTION_SETTINGS_SSM_PARAMETER` is set, the service attempts to load one JSON
object from AWS Systems Manager Parameter Store and use it as a settings source.

### Important Settings

- `postgres_dsn`
- `milvus_uri`
- `openai_api_key`
- `github_webhook_secret`
- `clone_base_dir`
- `temporal_address`
- `temporal_task_queue`
- `chunker_strategy`
- `embedding_strategy`

## Runtime and Operational Notes

Important implementation details:

- the HTTP service starts workflows, but the actual indexing work is expected to
  run on the Temporal worker defined in `services/ingestion/src/ingestion/temporal/worker.py`
- git operations use `clone_base_dir` as local working storage for repositories
- embedding work is batched inside workflows using `EMBED_BATCH_SIZE`
- branch status updates are persisted through dedicated activities rather than
  inline workflow state

## Current Limitations and Follow-Up Work

The most important gaps at the time of writing are:

- the service boundary itself is unauthenticated
- branch status values are stringly typed rather than enum-backed
- webhook processing only handles GitHub push events
- incremental indexing assumes local git state can be fetched and diffed successfully
- cleanup on failure happens after exceptions and is not transactional across all backends
- runtime docs for the wider system may still lag behind the actual ingestion pipeline

## Design Principles for Future Work

When extending this service, keep these constraints in place:

- orchestration should stay in Temporal workflows, not in HTTP handlers
- side-effecting work should remain decomposed into retryable activities
- PostgreSQL and Milvus updates should stay aligned through one ingestion pipeline
- branch status should continue to represent real persisted state, not inferred UI state
- runtime docs should describe the actual implemented pipeline, not a future indexing design
