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

    assert settings.resolved_llm_model() == "gpt-5.4-nano"
    assert settings.resolved_llm_reasoning_effort() == "none"


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
        "reasoning_effort": "none"
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
def test_ingestion_settings_resolved_llm_strategy_defaults_when_both_empty() -> None:
    settings = IngestionSettings(llm_strategy="", embedding_strategy="")
    assert settings.resolved_llm_strategy() == "bedrock"  # DEFAULT_LLM_STRATEGY


@pytest.mark.unit
def test_build_embedding_provider_openai() -> None:
    from ingestion.temporal.activities.wiki import _build_embedding_provider
    from ingestion.embedding.registry import EmbeddingStrategy
    from unittest.mock import MagicMock, patch

    settings = IngestionSettings(openai_api_key="sk-test")
    with patch("ingestion.temporal.activities.wiki.get_embedding_provider") as mock_get:
        mock_get.return_value = MagicMock()
        _build_embedding_provider(settings, EmbeddingStrategy.OPENAI)
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("api_key") == "sk-test"


@pytest.mark.unit
def test_build_embedding_provider_bedrock() -> None:
    from ingestion.temporal.activities.wiki import _build_embedding_provider
    from ingestion.embedding.registry import EmbeddingStrategy
    from unittest.mock import MagicMock, patch

    settings = IngestionSettings(embedding_model="amazon.titan-embed-text-v2:0", embedding_dimension=1024)
    with patch("ingestion.temporal.activities.wiki.get_embedding_provider") as mock_get:
        mock_get.return_value = MagicMock()
        _build_embedding_provider(settings, EmbeddingStrategy.BEDROCK)
        call_kwargs = mock_get.call_args.kwargs
        assert "dimensions" in call_kwargs


@pytest.mark.unit
def test_build_llm_provider_openai() -> None:
    from ingestion.temporal.activities.wiki import _build_llm_provider
    from ingestion.llm.registry import LLMStrategy
    from unittest.mock import MagicMock, patch

    settings = IngestionSettings(llm_strategy="openai", openai_api_key="sk-test")
    with patch("ingestion.temporal.activities.wiki.get_llm_provider") as mock_get:
        mock_get.return_value = MagicMock()
        _build_llm_provider(settings, LLMStrategy.OPENAI)
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("api_key") == "sk-test"


@pytest.mark.unit
def test_build_llm_provider_bedrock() -> None:
    from ingestion.temporal.activities.wiki import _build_llm_provider
    from ingestion.llm.registry import LLMStrategy
    from unittest.mock import MagicMock, patch

    settings = IngestionSettings(llm_strategy="bedrock")
    with patch("ingestion.temporal.activities.wiki.get_llm_provider") as mock_get:
        mock_get.return_value = MagicMock()
        _build_llm_provider(settings, LLMStrategy.BEDROCK)
        mock_get.assert_called_once()


@pytest.mark.unit
def test_raise_non_retryable_wiki_error_with_retryable_error() -> None:
    from ingestion.temporal.activities.wiki import _raise_non_retryable_wiki_error

    # A generic RuntimeError is retryable — should NOT raise ApplicationError
    exc = RuntimeError("transient failure")
    _raise_non_retryable_wiki_error(exc, phase="test")  # should not raise


@pytest.mark.unit
def test_raise_non_retryable_wiki_error_with_value_error() -> None:
    from ingestion.temporal.activities.wiki import _raise_non_retryable_wiki_error
    from temporalio.exceptions import ApplicationError

    exc = ValueError("bad config")
    with pytest.raises(ApplicationError, match="Non-retryable"):
        _raise_non_retryable_wiki_error(exc, phase="LLM initialization")


@pytest.mark.unit
def test_is_non_retryable_wiki_error_with_client_error_non_auth() -> None:
    from ingestion.temporal.activities.wiki import _is_non_retryable_wiki_error

    exc = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "Converse",
    )
    # ThrottlingException is retryable
    assert _is_non_retryable_wiki_error(exc) is False


@pytest.mark.unit
def test_is_non_retryable_wiki_error_with_message_fragment() -> None:
    from ingestion.temporal.activities.wiki import _is_non_retryable_wiki_error

    exc = RuntimeError("Invalid api key provided")
    assert _is_non_retryable_wiki_error(exc) is True

    exc2 = RuntimeError("No credentials found in environment")
    assert _is_non_retryable_wiki_error(exc2) is True


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
