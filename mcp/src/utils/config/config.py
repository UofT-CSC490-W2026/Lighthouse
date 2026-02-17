from functools import lru_cache

# from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings#, SettingsConfigDict

from .env import (
    DEBUG,
    APP_ENV,
)


class Settings(BaseSettings):
    """Runtime configuration for the MCP service."""

    service_name: str = "Lighthouse MCP Context Service"
    app_env: str = APP_ENV
    debug: bool = DEBUG


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()
