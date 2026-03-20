FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies (cached layer — only re-runs when lockfile or pyproject changes)
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY services/search/pyproject.toml services/search/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package search --frozen --no-dev --no-install-project

# Copy source and do final install
COPY services/search/src services/search/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package search --frozen --no-dev --no-editable


FROM python:3.11-slim-bookworm

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "search.main:app", "--host", "0.0.0.0", "--port", "8000"]
