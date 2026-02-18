"""Runtime settings for the pipeline worker service."""

from functools import lru_cache

from config_provider import bootstrap_runtime_config
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

bootstrap_runtime_config(service="pipeline")


class Settings(BaseSettings):
    """Runtime configuration contract for all pipeline worker processes."""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    debug: bool = True

    temporal_target_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue_runtime: str = Field(
        default="runtime-indexing",
        validation_alias=AliasChoices(
            "TEMPORAL_TASK_QUEUE_RUNTIME",
            "TEMPORAL_RUNTIME_TASK_QUEUE",
        ),
    )
    temporal_task_queue_offline: str = Field(
        default="offline-datasets",
        validation_alias=AliasChoices(
            "TEMPORAL_TASK_QUEUE_OFFLINE",
            "TEMPORAL_OFFLINE_TASK_QUEUE",
        ),
    )
    temporal_task_queue_mental_model: str = Field(
        default="mental-model",
        validation_alias=AliasChoices(
            "TEMPORAL_TASK_QUEUE_MENTAL_MODEL",
            "TEMPORAL_MENTAL_MODEL_TASK_QUEUE",
        ),
    )

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
    """Return a cached `Settings` instance for process-wide reuse."""
    return Settings()


settings = get_settings()
