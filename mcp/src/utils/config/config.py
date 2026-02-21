"""MCP runtime settings model and bootstrap."""

import json
from functools import lru_cache
from typing import Annotated

from config_provider import bootstrap_runtime_config
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from retrieval_vectors import DEFAULT_VECTOR_DIMENSIONS
from runtime_retrieval import RUNTIME_CHUNK_COLLECTION

bootstrap_runtime_config(service="mcp")


class Settings(BaseSettings):
    """Runtime configuration for the MCP service."""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "Lighthouse MCP Context Service"
    app_env: str = "local"
    debug: bool = True
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:6274",
            "http://127.0.0.1:6274",
        ]
    )

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
    runtime_milvus_collection: str = RUNTIME_CHUNK_COLLECTION
    runtime_milvus_vector_dimensions: int = Field(
        default=DEFAULT_VECTOR_DIMENSIONS,
        ge=8,
        le=4096,
    )
    s3_bucket: str | None = None
    aws_region: str = "us-east-1"
    github_read_token: SecretStr | None = None

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_cors_allow_origins(cls, value: str | list[str]) -> list[str]:
        """Accept comma-delimited, JSON array, or pre-parsed CORS origins."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(origin).strip() for origin in parsed if str(origin).strip()]
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()
