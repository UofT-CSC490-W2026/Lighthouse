from __future__ import annotations

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from shared.config import DEFAULT_EMBEDDING_STRATEGY
from shared.ssm import ssm_settings_sources

SSM_PARAMETER_ENV_VAR = "SEARCH_SETTINGS_SSM_PARAMETER"
DEFAULT_RERANK_MODEL = "rerank-v4.0-pro"


class SearchSettings(BaseSettings):
    """Configuration for the search service."""

    postgres_dsn: str = "postgresql://lighthouse:lighthouse@localhost:5432/lighthouse"
    milvus_uri: str = "http://localhost:19530"
    embedding_strategy: str = DEFAULT_EMBEDDING_STRATEGY
    embedding_model: str = ""
    openai_api_key: str = ""
    cohere_api_key: str = ""
    internal_service_token: str = ""
    rerank_model: str = DEFAULT_RERANK_MODEL

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

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
