FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies (cached layer — only re-runs when lockfile or pyproject changes)
COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
COPY services/search/pyproject.toml services/search/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package search --frozen --no-dev --no-install-project

# Copy source
COPY packages/shared/src packages/shared/src
COPY services/search/src services/search/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package search --frozen --no-dev


FROM python:3.11-slim-bookworm

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages/shared/src /app/packages/shared/src
COPY --from=builder /app/services/search/src /app/services/search/src

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/services/search/src"

EXPOSE 8000

CMD ["uvicorn", "search.main:app", "--host", "0.0.0.0", "--port", "8000"]
