from __future__ import annotations

from botocore.exceptions import ClientError
import pytest

from ingestion.temporal.activities.wiki import _is_non_retryable_wiki_error
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
