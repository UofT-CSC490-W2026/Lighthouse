from __future__ import annotations

from pydantic_settings import BaseSettings


class IngestionSettings(BaseSettings):
    """Configuration for the ingestion service."""

    postgres_dsn: str = "postgresql://lighthouse:lighthouse@localhost:5432/lighthouse"
    milvus_uri: str = "http://localhost:19530"
    openai_api_key: str = ""
    github_webhook_secret: str = ""
    clone_base_dir: str = "/tmp/lighthouse_repos"
    temporal_address: str = "localhost:7233"
    temporal_task_queue: str = "ingestion"

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}
