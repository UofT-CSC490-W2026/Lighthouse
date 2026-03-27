from __future__ import annotations

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from shared.ssm import ssm_settings_sources
from shared.config import EMBEDDING_MODEL

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
    temporal_task_queue: str = "ingestion"
    chunker_strategy: str = "sliding_window"
    embedding_strategy: str = "openai"
    embedding_model: str = EMBEDDING_MODEL

    #model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', env_prefix="", extra="ignore")

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
