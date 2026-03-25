from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from shared.ssm import get_ssm_client, ssm_settings_sources, _get_parameter_value

SSM_PARAMETER_ENV_VAR = "MCP_SERVER_SETTINGS_SSM_PARAMETER"


class Settings(BaseSettings):
    """Typed runtime settings for the MCP service."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_ignore_empty=True,
        extra="ignore",
    )

    debug: bool = Field(
        default=True,
        validation_alias=AliasChoices("DEBUG", "debug"),
    )
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        validation_alias=AliasChoices("CORS_ALLOW_ORIGINS", "cors_allow_origins"),
    )
    postgres_dsn: str | None = Field(
        default=None,
        validation_alias=AliasChoices("POSTGRES_DSN", "postgres_dsn"),
    )
    github_oauth_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_OAUTH_CLIENT_ID",
            "github_oauth_client_id",
        ),
    )
    github_oauth_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_OAUTH_CLIENT_SECRET",
            "github_oauth_client_secret",
        ),
    )
    github_oauth_callback_url: str = Field(
        default="http://localhost:8000/v1/auth/github/callback",
        validation_alias=AliasChoices(
            "GITHUB_OAUTH_CALLBACK_URL",
            "github_oauth_callback_url",
        ),
    )
    session_encryption_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SESSION_ENCRYPTION_KEY",
            "session_encryption_key",
        ),
    )
    web_client_url: str = Field(
        default="http://localhost:5173",
        validation_alias=AliasChoices("WEB_CLIENT_URL", "web_client_url"),
    )
    session_ttl_hours: int = Field(
        default=168,
        validation_alias=AliasChoices("SESSION_TTL_HOURS", "session_ttl_hours"),
    )
    mcp_server_settings_ssm_parameter: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            SSM_PARAMETER_ENV_VAR,
            "mcp_server_settings_ssm_parameter",
        ),
    )
    aws_region: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
            "aws_region",
        ),
    )
    search_service_url: str = Field(
        default="http://localhost:8002",
        validation_alias=AliasChoices(
            "SEARCH_SERVICE_URL",
            "search_service_url",
        ),
    )
    ingestion_service_url: str = Field(
        default="http://localhost:8001",
        validation_alias=AliasChoices(
            "INGESTION_SERVICE_URL",
            "ingestion_service_url",
        ),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load env and dotenv values first, then fall back to SSM defaults."""
        return ssm_settings_sources(
            SSM_PARAMETER_ENV_VAR,
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached service settings instance."""
    return Settings()


def reload_settings() -> Settings:
    """Clear cached settings and SSM helpers, then reload configuration."""
    get_settings.cache_clear()
    get_ssm_client.cache_clear()
    _get_parameter_value.cache_clear()
    return get_settings()


DEBUG = get_settings().debug
