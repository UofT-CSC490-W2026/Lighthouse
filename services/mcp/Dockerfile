FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies (cached layer — only re-runs when lockfile or pyproject changes)
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY services/mcp/pyproject.toml services/mcp/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package lighthouse-mcp --frozen --no-dev --no-install-project

# Copy source and do final install
COPY services/mcp/src services/mcp/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package lighthouse-mcp --frozen --no-dev --no-editable


FROM python:3.11-slim-bookworm

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
