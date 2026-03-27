FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY evaluation/pyproject.toml evaluation/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package lighthouse-eval --frozen --no-dev --no-install-project


FROM python:3.11-slim-bookworm

WORKDIR /workspace

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/workspace/evaluation/src" \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    docker.io \
    git \
    patch \
    && rm -rf /var/lib/apt/lists/*

CMD ["sh"]
