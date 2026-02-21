"""Runtime settings for the pipeline worker service."""

from functools import lru_cache

from config_provider import bootstrap_runtime_config
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from retrieval_vectors import DEFAULT_VECTOR_DIMENSIONS
from runtime_retrieval import RUNTIME_CHUNK_COLLECTION

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
    runtime_milvus_write_enabled: bool = True
    runtime_milvus_collection: str = RUNTIME_CHUNK_COLLECTION
    runtime_milvus_vector_dimensions: int = Field(
        default=DEFAULT_VECTOR_DIMENSIONS,
        ge=8,
        le=4096,
    )
    s3_bucket: str | None = None
    aws_region: str = "us-east-1"

    github_read_token: SecretStr | None = None
    validate_milvus_on_startup: bool = False
    validate_s3_on_startup: bool = False
    run_worker_on_startup: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached `Settings` instance for process-wide reuse."""
    return Settings()


settings = get_settings()
