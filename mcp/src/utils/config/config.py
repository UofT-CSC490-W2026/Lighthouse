from functools import lru_cache

from config_provider import bootstrap_runtime_config
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    cors_allow_origins: list[str] = Field(
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
    s3_bucket: str | None = None
    aws_region: str = "us-east-1"
    github_read_token: SecretStr | None = None

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_cors_allow_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()
