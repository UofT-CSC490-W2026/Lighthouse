"""Runtime settings for the pipeline worker service."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    debug: bool = True

    temporal_target_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue_runtime: str = "runtime-indexing"
    temporal_task_queue_offline: str = "offline-datasets"
    temporal_task_queue_mental_model: str = "mental-model"

    postgres_dsn: str | None = None
    milvus_uri: str = "http://localhost:19530"
    milvus_user: str | None = None
    milvus_password: SecretStr | None = None
    milvus_database: str = "default"
    s3_bucket: str | None = None
    aws_region: str = "us-east-1"

    github_read_token: SecretStr | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

