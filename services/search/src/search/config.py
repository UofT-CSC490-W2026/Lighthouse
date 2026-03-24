from __future__ import annotations

from pydantic_settings import BaseSettings


class SearchSettings(BaseSettings):
    """Configuration for the search service."""

    postgres_dsn: str = "postgresql://lighthouse:lighthouse@localhost:5432/lighthouse"
    milvus_uri: str = "http://localhost:19530"
    openai_api_key: str = ""

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}
