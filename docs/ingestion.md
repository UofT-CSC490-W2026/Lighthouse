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
- webhook-driven incremental indexing expects an existing clone under
  `clone_base_dir` (same layout as full indexing); without it, fetch/clone cannot
  succeed with the empty URL used in the incremental workflow

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
- git activities clone, fetch, list files changed between commits, and diff
  repositories
- chunking activities read files and write staging chunks
- embedding activities generate embeddings in batches (workflows fan out multiple
  batch activities in parallel)
- storage activities delete old data, move staged chunks to final storage,
  publish incremental batches (swap active file versions), remove superseded
  chunks after publish, and clean staging rows on failure

`delete_chunks_for_files` is implemented and registered on the worker for tests
and reuse, but the current workflows do not call it; incremental publishing uses
`publish_staged_chunks` and `cleanup_inactive_chunks` instead.

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

- `index-<github_repo_id>` for the parent `IndexRepositoryWorkflow`
- `index-branch-<github_repo_id>-<branch>` for each child `IndexBranchWorkflow`

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

`IndexBranchWorkflow` runs as a child workflow (see workflow IDs above) and
currently performs:

1. mark the branch as `indexing` (optionally persisting an encrypted GitHub token
   when provided)
2. clone or fetch the repository; capture the branch `HEAD` as `latest_commit`
3. chunk the entire branch into the staging table (`chunker_strategy` defaults to
   `sliding_window` on `ChunkFilesInput` / `IndexBranchInput`)
4. if there are no chunks, mark the branch as `indexed` with
   `last_indexed_commit` set from the git result and stop
5. delete **all** existing final chunks for that repository branch (PostgreSQL
   and Milvus)
6. embed staged chunks in batches of `EMBED_BATCH_SIZE` (512), running **all**
   batch embedding activities concurrently via `asyncio.gather`
7. `store_chunks`: move the staging batch into final PostgreSQL rows and Milvus
8. mark the branch as `indexed` with `last_indexed_commit` from the git step

On failure it:

- marks the branch as `failed`
- cleans up staging rows if a batch was already created (`cleanup_staging`)
- re-raises the error so Temporal sees the failure

## Incremental Indexing Flow

Incremental indexing is implemented in
`services/ingestion/src/ingestion/temporal/workflows/incremental.py`.

The current flow is:

1. `ensure_repository_record` with `repo_url` empty (upsert by `github_repo_id` /
   `full_name` only) to resolve `repository_id`
2. mark the branch as `indexing`
3. `git_clone_or_fetch` with an empty `repo_url` and `repo_dir_name` set to the
   string form of `github_repo_id`. If that directory already exists under
   `clone_base_dir` from a prior full index, the worker fetches and checks out
   the branch; if not, clone would require a URL, so **incremental indexing
   assumes a clone already exists** (typically after `POST /index`)
4. `get_changed_files` between `before_commit` and `after_commit`
5. if there are no changed files, mark the branch as `indexed` with
   `last_indexed_commit` = `after_commit` and stop
6. `chunk_files` with `file_filter` set to the changed paths (default chunker
   strategy)
7. if `chunk_count > 0`, embed staged rows in batches of `EMBED_BATCH_SIZE`, with
   all batch activities run concurrently
8. `publish_staged_chunks`: publishes the staging batch, updates per-file active
   versions (`IndexedFile` / `publish_id` on `Chunk`), and returns
   `cleanup_targets` for the previous publish IDs that are no longer active
9. mark the branch as `indexed` with `last_indexed_commit` = `after_commit`
10. best-effort `cleanup_inactive_chunks` for those targets (logs a warning and
    continues if cleanup fails)

Incremental indexing does **not** call `store_chunks` (full replace). It uses
publish + cleanup so concurrent search readers see a consistent switch per file.

On failure it follows the same `failed` status and `cleanup_staging` pattern as
the full branch workflow when a `batch_id` was allocated.

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

- `delete_existing_chunks`: remove all chunks for a branch from PostgreSQL and
  Milvus (used by full branch indexing before replacing with a new batch)
- `delete_chunks_for_files`: remove chunks for a given file set (not used by the
  current workflows)
- `store_chunks`: move a full staging batch to final PostgreSQL storage and Milvus
  (full branch path)
- `publish_staged_chunks`: publish an incremental staging batch, flip active file
  versions, and return targets for deleting superseded chunk rows
- `cleanup_inactive_chunks`: delete Milvus/Postgres rows for those superseded
  publish IDs after the new version is active
- `cleanup_staging`: remove staging rows (typically on workflow failure)

PostgreSQL holds final chunk content (with per-file `publish_id` versioning for
incremental updates); Milvus holds vector search state aligned with the same
pipeline.

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
- `publish_id` (identifies which publish generation this row belongs to; full
  branch moves use the default `legacy` unless overridden by the chunk service)

### `IndexedFile`

Tracks, per repository branch and file path, which `publish_id` is currently
active. Incremental `publish_staged_chunks` updates this so search can follow
the latest published version per file.

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
- embedding work is batched inside workflows using `EMBED_BATCH_SIZE`; each
  workflow schedules one Temporal activity per batch and runs all batch
  activities for a step concurrently
- branch status updates are persisted through dedicated activities rather than
  inline workflow state

## Current Limitations and Follow-Up Work

The most important gaps at the time of writing are:

- the service boundary itself is unauthenticated
- branch status values are stringly typed rather than enum-backed
- webhook processing only handles GitHub push events
- incremental indexing requires an on-disk clone and successful fetch/diff between
  the push’s `before` and `after` commits
- cleanup on failure happens after exceptions and is not transactional across all backends

## Design Principles for Future Work

When extending this service, keep these constraints in place:

- orchestration should stay in Temporal workflows, not in HTTP handlers
- side-effecting work should remain decomposed into retryable activities
- PostgreSQL and Milvus updates should stay aligned through one ingestion pipeline
- branch status should continue to represent real persisted state, not inferred UI state
- runtime docs should describe the actual implemented pipeline, not a future indexing design
