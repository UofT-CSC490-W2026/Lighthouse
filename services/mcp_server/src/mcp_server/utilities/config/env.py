from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

SSM_PARAMETER_ENV_VAR = "MCP_SERVER_SETTINGS_SSM_PARAMETER"


def _ssm_parameter_name_from_env() -> str:
    """Resolve the SSM parameter name pointer from the environment."""
    return os.getenv(SSM_PARAMETER_ENV_VAR, "").strip()


def _dedupe(values: list[str]) -> list[str]:
    """Return the input list without empty values or duplicates, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _field_keys(field_name: str, field: FieldInfo) -> list[str]:
    """Collect the possible payload or environment keys for a settings field."""
    keys = [field_name]

    alias = field.validation_alias
    if isinstance(alias, str):
        keys.insert(0, alias)
    elif isinstance(alias, AliasChoices):
        keys = [choice for choice in alias.choices if isinstance(choice, str)] + keys

    if isinstance(field.alias, str):
        keys.insert(0, field.alias)

    return _dedupe(keys)


@lru_cache(maxsize=None)
def get_ssm_client(region_name: str | None = None) -> Any:
    """Create and cache an SSM client for the configured AWS region."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "boto3 must be installed to load MCP settings from AWS SSM Parameter Store."
        ) from exc

    kwargs: dict[str, Any] = {}
    if region_name:
        kwargs["region_name"] = region_name
    return boto3.client("ssm", **kwargs)


@lru_cache(maxsize=None)
def _get_parameter_value(parameter_name: str, region_name: str | None = None) -> str:
    """Fetch and decrypt a raw settings payload from SSM."""
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise RuntimeError(
            "botocore is required to load MCP settings from AWS SSM Parameter Store."
        ) from exc

    try:
        response = get_ssm_client(region_name).get_parameter(
            Name=parameter_name,
            WithDecryption=True,
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(
            f"Failed to load MCP settings from SSM parameter {parameter_name!r}."
        ) from exc

    value = response["Parameter"]["Value"]
    if not isinstance(value, str):
        raise RuntimeError(
            f"Expected SSM parameter {parameter_name!r} to contain a string value."
        )
    return value


def _get_region_name() -> str | None:
    """Resolve the AWS region from the process environment."""
    for key in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def _load_parameter_payload(
    parameter_name: str,
    region_name: str | None = None,
) -> dict[str, Any]:
    """Decode the SSM settings payload as a JSON object."""
    raw_value = _get_parameter_value(parameter_name, region_name)
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"SSM parameter {parameter_name!r} must contain a JSON object."
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"SSM parameter {parameter_name!r} must decode to a JSON object."
        )
    return payload


class SSMSettingsSource(PydanticBaseSettingsSource):
    """Load settings defaults from a single JSON blob stored in AWS SSM."""

    def get_field_value(
        self,
        field: FieldInfo,
        field_name: str,
    ) -> tuple[Any, str, bool]:
        """Defer field extraction until the source is invoked in bulk."""
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        """Load and map SSM payload fields onto the settings model."""
        parameter_name = _ssm_parameter_name_from_env()
        if not parameter_name:
            return {}

        payload = _load_parameter_payload(parameter_name, _get_region_name())
        data: dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            for key in _field_keys(field_name, field):
                if key not in payload:
                    continue

                value = payload[key]
                if isinstance(value, str) and self.field_is_complex(field):
                    value = self.prepare_field_value(field_name, field, value, True)

                data[field_name] = value
                break

        return data


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
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            SSMSettingsSource(settings_cls),
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
