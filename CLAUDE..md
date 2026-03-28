# Repository Guidelines

## Project Structure & Module Organization

`lighthouse` is a monorepo. Python services live under `services/`: `ingestion`, `search`, and `mcp_server` each keep app code in `src/<name>` and tests in `tests/`. The frontend lives in `services/web` with React/Vite code under `src/`. Shared Python libraries are in `packages/` (`db`, `embedding`, `shared`, `testing`, `vectordb`). Infrastructure code is under `infra/`, Docker assets under `docker/`, and longer design/testing notes under `docs/`. Ignore `assignments/` for product development.

## Build, Test, and Development Commands

Install Python workspace dependencies with `uv sync --all-packages --dev`. Start local infra with `docker compose up -d`.

- `uv run pytest`: run the full Python test suite.
- `uv run pytest -m unit|integration|e2e`: run one test slice.
- `uv run pytest --cov`: generate coverage locally.
- `uv run ruff check .`: lint Python code.
- `uv run ruff format .`: format Python code.
- `uv run ty check`: run static type checks configured at the repo root.
- `npm --prefix services/web run dev`: start the frontend locally.
- `npm --prefix services/web run build`: build the frontend bundle.

## Coding Style & Naming Conventions

Python targets 3.11, uses 4-space indentation, double quotes, and Ruff formatting with a 100-character line length. Follow existing package/module naming: `snake_case` files and functions, `PascalCase` classes, `UPPER_SNAKE_CASE` constants. Frontend code uses TypeScript with 2-space indentation, `PascalCase` component files such as `RepoCard.tsx`, and colocated helpers in `src/lib`.

## Testing Guidelines

Place tests beside the owning package or service and name them `test_<behavior>.py`. Reuse shared fixtures from `packages/testing/src/testing_utils` instead of rebuilding containers or mocks. Mark tests explicitly with `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.e2e`. Coverage is reported in CI, but the current threshold is informational (`--cov-fail-under=0`). There is no frontend test runner configured yet.
