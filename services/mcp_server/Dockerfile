FROM python:3.11-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Avoid relying on GHCR for the builder image, which can fail with 403 token errors.
RUN python -m pip install --no-cache-dir uv

# Install dependencies (cached layer — only re-runs when lockfile or pyproject changes)
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY services/mcp_server/pyproject.toml services/mcp_server/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package mcp-server --frozen --no-dev --no-install-project

# Copy source and do final install
COPY services/mcp_server/src services/mcp_server/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package mcp-server --frozen --no-dev --no-editable


FROM python:3.11-slim-bookworm

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["uvicorn", "mcp_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
