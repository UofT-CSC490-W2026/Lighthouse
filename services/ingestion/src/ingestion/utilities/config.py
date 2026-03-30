from __future__ import annotations

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from shared.config import (
    DEFAULT_LLM_STRATEGY,
    OPENAI_REASONING_EFFORT,
    default_llm_model,
)
from shared.ssm import ssm_settings_sources

SSM_PARAMETER_ENV_VAR = "INGESTION_SETTINGS_SSM_PARAMETER"


class IngestionSettings(BaseSettings):
    """Configuration for the ingestion service."""

    postgres_dsn: str = "postgresql://lighthouse:lighthouse@localhost:5432/lighthouse"
    milvus_uri: str = "http://localhost:19530"
    openai_api_key: str = ""
    github_webhook_secret: str = ""
    internal_service_token: str = ""
    clone_base_dir: str = "/tmp/lighthouse_repos"
    temporal_address: str = "localhost:7233"
    temporal_api_key: str = ""
    temporal_namespace: str = "default"
    temporal_task_queue: str = "ingestion"
    chunker_strategy: str = "sliding_window"
    embedding_strategy: str = "openai"
    embedding_model: str = ""
    embedding_dimension: int = 0
    llm_strategy: str = DEFAULT_LLM_STRATEGY
    llm_model: str = ""
    llm_reasoning_effort: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
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
        return ssm_settings_sources(
            SSM_PARAMETER_ENV_VAR,
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    def resolved_llm_strategy(self) -> str:
        normalized = self.llm_strategy.strip().lower()
        if normalized:
            return normalized

        fallback = self.embedding_strategy.strip().lower()
        if fallback:
            return fallback
        return DEFAULT_LLM_STRATEGY

    def resolved_llm_model(self) -> str:
        configured = self.llm_model.strip()
        if configured:
            return configured
        return default_llm_model(self.resolved_llm_strategy())

    def resolved_llm_reasoning_effort(self) -> str:
        configured = self.llm_reasoning_effort.strip()
        if configured:
            return configured
        if self.resolved_llm_strategy() == "openai":
            return OPENAI_REASONING_EFFORT
        return ""

    def resolved_temporal_namespace(self) -> str:
        configured = self.temporal_namespace.strip()
        if configured:
            return configured
        return "default"

    def temporal_uses_tls(self) -> bool:
        address = self.temporal_address.strip().lower()
        return bool(self.temporal_api_key.strip()) or ".tmprl.cloud" in address

    def temporal_connect_kwargs(self) -> dict[str, str | bool]:
        kwargs: dict[str, str | bool] = {
            "namespace": self.resolved_temporal_namespace(),
        }
        api_key = self.temporal_api_key.strip()
        if api_key:
            kwargs["api_key"] = api_key
        if self.temporal_uses_tls():
            kwargs["tls"] = True
        return kwargs
