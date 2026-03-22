"""Application settings loaded from environment variables."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_dsn: str = "postgresql://lighthouse:lighthouse@localhost:5432/lighthouse"
    github_oauth_client_id: str = ""
    github_oauth_client_secret: SecretStr = SecretStr("")
    github_oauth_callback_url: str = "http://localhost:8000/v1/auth/github/callback"
    session_encryption_key: SecretStr = SecretStr("")
    web_client_url: str = "http://localhost:5173"
    session_ttl_hours: int = 168
    debug: bool = False
    cors_allow_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
