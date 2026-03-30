# Testing In Lighthouse

This repository uses a workspace-level Python testing setup built around `pytest`. Most automated tests live beside the Python packages and services under `packages/*/tests` and `services/*/tests`, with shared fixtures in `packages/testing`.

## Overview

- Test runner: `pytest`
- Async support: `pytest-asyncio`
- Coverage: `pytest-cov`
- Test dependency management: `uv`
- Integration test infrastructure: `testcontainers` for Postgres and Milvus
- Workflow testing: `temporalio.testing` for ingestion workflow tests

The root [`pyproject.toml`](../pyproject.toml) is the source of truth for test discovery, markers, asyncio mode, and coverage settings.

## Where Tests Live

The root `pytest` config discovers tests from these directories:

- `packages/db/tests`
- `packages/vectordb/tests`
- `packages/embedding/tests`
- `packages/shared/tests`
- `services/ingestion/tests`
- `services/search/tests`
- `services/mcp_server/tests`

Tests are generally organized by scope:

- `unit/`: pure logic tests with no external infrastructure
- `integration/`: tests that rely on Postgres and/or Milvus testcontainers
- `e2e/`: higher-level API or workflow tests, including FastAPI and Temporal flows

As of March 26, 2026, the suite collects `234` tests.

## Test Markers

The repo defines three markers in [`pyproject.toml`](../pyproject.toml):

- `unit`: pure unit tests with no external dependencies
- `integration`: tests requiring Postgres/Milvus testcontainers
- `e2e`: end-to-end tests with FastAPI/Temporal

This lets you run a specific slice of the suite instead of everything.

## Running Tests Locally

Install dependencies first:

```sh
uv sync --all-packages --dev
```

Run the full suite:

```sh
uv run pytest
```

Run with coverage:

```sh
uv run pytest --cov
```

Run by marker:

```sh
uv run pytest -m unit
uv run pytest -m integration
uv run pytest -m e2e
```

Run a single file:

```sh
uv run pytest services/search/tests/unit/test_rrf_fusion.py
```

Run a single test:

```sh
uv run pytest services/mcp_server/tests/unit/test_auth_helpers.py -k extract_bearer_valid
```

If `uv` cannot write to the default cache in a restricted environment, set a writable cache directory:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
```

## Shared Test Infrastructure

Reusable test fixtures live in [`packages/testing/src/testing_utils`](../packages/testing/src/testing_utils).

Important shared pieces:

- [`containers.py`](../packages/testing/src/testing_utils/containers.py): session-scoped Postgres and Milvus testcontainers plus derived DSN/URI fixtures
- [`db_fixtures.py`](../packages/testing/src/testing_utils/db_fixtures.py): database manager fixtures used across services and packages
- [`milvus_fixtures.py`](../packages/testing/src/testing_utils/milvus_fixtures.py): Milvus client fixtures
- [`mock_embedding.py`](../packages/testing/src/testing_utils/mock_embedding.py): deterministic embedding mock for tests that should not call a real embedding backend

Most package and service `conftest.py` files import these shared fixtures instead of redefining infrastructure setup.

## Service-Specific Notes

### `packages/*`

- `packages/shared` and much of `packages/embedding` are mostly unit-tested
- `packages/db` and `packages/vectordb` include integration tests against real Postgres or Milvus containers

### `services/ingestion`

- Has unit, integration, and e2e coverage
- Uses testcontainers for storage dependencies
- Uses `temporalio.testing.ActivityEnvironment` and `WorkflowEnvironment.start_time_skipping()` for workflow tests
- Includes e2e tests for FastAPI endpoints and Temporal workflows

### `services/search`

- Uses shared Postgres and Milvus fixtures from `packages/testing`
- Has unit coverage for ranking logic, integration coverage for hybrid search, and e2e coverage for HTTP endpoints

### `services/mcp_server`

- Has unit, integration, and e2e coverage
- Integration tests focus on authentication and token lifecycle behavior
- E2E tests exercise HTTP endpoints

### `services/web`

There is currently no frontend test runner or frontend test suite configured in [`services/web/package.json`](../services/web/package.json). The existing automated test setup is effectively Python-only.

## Coverage And CI

CI is defined in [`.github/workflows/tests.yml`](../.github/workflows/tests.yml).

On every pull request and every push to `main`, GitHub Actions:

1. Sets up Python 3.11 and `uv`
2. Installs workspace dependencies with `uv sync --all-packages --dev`
3. Runs `uv run pytest --cov --cov-fail-under=0 --cov-report=xml --cov-report=term-missing`

The workflow also:

- Generates a coverage summary from `coverage.xml`
- Updates the coverage section in [`README.md`](../README.md) on pushes to `main`
- Posts or updates a PR comment with the current total coverage on pull requests

There is currently no minimum coverage gate because CI uses `--cov-fail-under=0`.

## Practical Conventions

When adding tests in this repo:

- Put them in the nearest package or service under `tests/`
- Use the existing `unit`, `integration`, and `e2e` split
- Reuse fixtures from `packages/testing` where possible
- Mark tests explicitly with `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.e2e`
- Prefer mock providers for embeddings in unit tests rather than calling external APIs
- Keep infrastructure-heavy tests in integration/e2e suites so unit runs stay fast
