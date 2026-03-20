FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies (cached layer — only re-runs when lockfile or pyproject changes)
COPY pyproject.toml uv.lock ./
COPY services/mcp/pyproject.toml services/mcp/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package mcp --frozen --no-dev --no-install-project

# Copy source
COPY services/mcp/src services/mcp/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package mcp --frozen --no-dev


FROM python:3.11-slim-bookworm

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/services/mcp/src /app/services/mcp/src

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/services/mcp/src"

EXPOSE 8000

CMD ["python", "mcp/main.py"]
