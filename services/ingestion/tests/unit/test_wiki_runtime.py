from __future__ import annotations

from botocore.exceptions import ClientError
import pytest

from ingestion.llm import LLMStrategy
from ingestion.temporal.activities.wiki import (
    _build_llm_request_kwargs,
    _is_non_retryable_wiki_error,
)
from ingestion.utilities.config import IngestionSettings
from llm import BedrockLLMProvider


class _FakeBedrockClient:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _bedrock_response(text: str) -> dict[str, object]:
    return {
        "output": {
            "message": {
                "content": [
                    {"text": text},
                ]
            }
        }
    }


@pytest.mark.unit
def test_ingestion_settings_default_wiki_llm_strategy_is_bedrock() -> None:
    settings = IngestionSettings()

    assert settings.resolved_llm_strategy() == "bedrock"
    assert settings.resolved_llm_model() == "us.amazon.nova-lite-v1:0"
    assert settings.resolved_llm_reasoning_effort() == ""


@pytest.mark.unit
def test_ingestion_settings_openai_reasoning_defaults_to_shared_value() -> None:
    settings = IngestionSettings(llm_strategy="openai")

    assert settings.resolved_llm_model() == "gpt-5.4-mini"
    assert settings.resolved_llm_reasoning_effort() == "low"


@pytest.mark.unit
def test_ingestion_settings_temporal_defaults_are_local_friendly() -> None:
    settings = IngestionSettings()

    assert settings.resolved_temporal_namespace() == "default"
    assert settings.temporal_uses_tls() is False
    assert settings.temporal_connect_kwargs() == {"namespace": "default"}


@pytest.mark.unit
def test_ingestion_settings_temporal_cloud_enables_namespace_api_key_and_tls() -> None:
    settings = IngestionSettings(
        temporal_address="my-namespace.tmprl.cloud:7233",
        temporal_namespace="my-namespace.a1b2c",
        temporal_api_key="secret-key",
    )

    assert settings.temporal_uses_tls() is True
    assert settings.temporal_connect_kwargs() == {
        "namespace": "my-namespace.a1b2c",
        "api_key": "secret-key",
        "tls": True,
    }


@pytest.mark.unit
def test_ingestion_settings_temporal_cloud_enables_tls_without_api_key() -> None:
    settings = IngestionSettings(
        temporal_address="my-namespace.tmprl.cloud:7233",
        temporal_namespace="my-namespace.a1b2c",
        temporal_api_key="",
    )

    assert settings.temporal_connect_kwargs() == {
        "namespace": "my-namespace.a1b2c",
        "tls": True,
    }


@pytest.mark.unit
def test_ingestion_settings_reasoning_effort_prefers_explicit_override() -> None:
    settings = IngestionSettings(llm_strategy="openai", llm_reasoning_effort="medium")

    assert settings.resolved_llm_reasoning_effort() == "medium"


@pytest.mark.unit
def test_build_llm_request_kwargs_includes_reasoning_for_openai() -> None:
    settings = IngestionSettings(llm_strategy="openai")

    assert _build_llm_request_kwargs(settings, LLMStrategy.OPENAI) == {
        "reasoning_effort": "low"
    }


@pytest.mark.unit
def test_build_llm_request_kwargs_omits_reasoning_for_bedrock() -> None:
    settings = IngestionSettings(llm_strategy="bedrock")

    assert _build_llm_request_kwargs(settings, LLMStrategy.BEDROCK) == {}


@pytest.mark.unit
def test_bedrock_llm_provider_complete_uses_converse_messages() -> None:
    client = _FakeBedrockClient(_bedrock_response("hello from bedrock"))
    provider = BedrockLLMProvider(client=client, model="us.amazon.nova-lite-v1:0")

    result = provider.complete(
        [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Say hello."},
        ]
    )

    assert result == "hello from bedrock"
    assert client.calls[0]["modelId"] == "us.amazon.nova-lite-v1:0"
    assert client.calls[0]["system"] == [{"text": "Be concise."}]


@pytest.mark.unit
def test_bedrock_llm_provider_complete_json_extracts_json_object() -> None:
    client = _FakeBedrockClient(
        _bedrock_response('Here you go:\n{"title": "Docs", "sections": []}')
    )
    provider = BedrockLLMProvider(client=client, model="us.amazon.nova-lite-v1:0")

    result = provider.complete_json([{"role": "user", "content": "Return JSON."}])

    assert result == {"title": "Docs", "sections": []}


@pytest.mark.unit
def test_invalid_bedrock_model_error_is_non_retryable() -> None:
    exc = ClientError(
        {
            "Error": {
                "Code": "ValidationException",
                "Message": "The provided model identifier is invalid.",
            }
        },
        "Converse",
    )

    assert _is_non_retryable_wiki_error(exc) is True
