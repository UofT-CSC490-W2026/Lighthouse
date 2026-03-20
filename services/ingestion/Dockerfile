FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies (cached layer — only re-runs when lockfile or pyproject changes)
COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
COPY services/ingestion/pyproject.toml services/ingestion/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package ingestion --frozen --no-dev --no-install-project

# Copy source
COPY packages/shared/src packages/shared/src
COPY services/ingestion/src services/ingestion/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package ingestion --frozen --no-dev


FROM python:3.11-slim-bookworm

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages/shared/src /app/packages/shared/src
COPY --from=builder /app/services/ingestion/src /app/services/ingestion/src

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/services/ingestion/src"

EXPOSE 8000

CMD ["uvicorn", "ingestion.main:app", "--host", "0.0.0.0", "--port", "8000"]
