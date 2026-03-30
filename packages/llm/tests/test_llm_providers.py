from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from llm.bedrock_provider import (
    BedrockLLMProvider,
    _as_mapping,
    _build_bedrock_message_payload,
    _extract_text_blocks,
    _parse_json_response,
)
from llm.openai_provider import OpenAILLMProvider


# ── BedrockLLMProvider helpers ────────────────────────────────────────────────


@pytest.mark.unit
def test_build_bedrock_message_payload_skips_empty_content():
    payload = _build_bedrock_message_payload(
        [
            {"role": "system", "content": ""},
            {"role": "user", "content": "hello"},
        ]
    )
    # Empty content message is skipped; only the user message remains
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"
    assert "system" not in payload


@pytest.mark.unit
def test_build_bedrock_message_payload_normalizes_assistant_role():
    payload = _build_bedrock_message_payload(
        [{"role": "assistant", "content": "sure"}]
    )
    assert payload["messages"][0]["role"] == "assistant"


@pytest.mark.unit
def test_extract_text_blocks_returns_empty_string_for_non_list_content():
    response = {"output": {"message": {"content": "not a list"}}}
    assert _extract_text_blocks(response) == ""


@pytest.mark.unit
def test_extract_text_blocks_skips_non_mapping_blocks():
    response = {
        "output": {
            "message": {
                "content": ["string_block", {"text": "valid block"}]
            }
        }
    }
    result = _extract_text_blocks(response)
    assert result == "valid block"


@pytest.mark.unit
def test_parse_json_response_returns_empty_dict_for_blank_string():
    assert _parse_json_response("") == {}
    assert _parse_json_response("   ") == {}


@pytest.mark.unit
def test_parse_json_response_extracts_embedded_json_object():
    result = _parse_json_response('Here is the result:\n{"key": "value"}\n')
    assert result == {"key": "value"}


@pytest.mark.unit
def test_parse_json_response_raises_for_invalid_json_without_braces():
    with pytest.raises(json.JSONDecodeError):
        _parse_json_response("not json at all")


@pytest.mark.unit
def test_parse_json_response_raises_for_non_dict_json():
    with pytest.raises(ValueError, match="did not return a JSON object"):
        _parse_json_response("[1, 2, 3]")


@pytest.mark.unit
def test_as_mapping_returns_empty_dict_for_non_mapping():
    assert _as_mapping(None) == {}
    assert _as_mapping(42) == {}
    assert _as_mapping([1, 2]) == {}


@pytest.mark.unit
def test_as_mapping_returns_dict_for_mapping():
    d = {"key": "value"}
    assert _as_mapping(d) is d


# ── BedrockLLMProvider – boto3 client initialization ─────────────────────────


@pytest.mark.unit
@patch("llm.bedrock_provider.boto3.client")
@patch("llm.bedrock_provider.prefer_explicit_aws_credentials")
def test_bedrock_llm_provider_creates_boto3_client_when_none(
    mock_prefer, mock_boto_client
):
    """When client is None, BedrockLLMProvider should create a boto3 client."""
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client

    provider = BedrockLLMProvider(region_name="us-east-1")

    mock_prefer.assert_called_once()
    mock_boto_client.assert_called_once_with(
        "bedrock-runtime", region_name="us-east-1"
    )
    assert provider.client is mock_client


@pytest.mark.unit
@patch("llm.bedrock_provider.boto3.client")
@patch("llm.bedrock_provider.prefer_explicit_aws_credentials")
def test_bedrock_llm_provider_creates_boto3_client_without_region(
    mock_prefer, mock_boto_client
):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client

    provider = BedrockLLMProvider()

    mock_boto_client.assert_called_once_with("bedrock-runtime")
    assert provider.client is mock_client


# ── BedrockLLMProvider – complete / complete_json ─────────────────────────────


@pytest.mark.unit
def test_bedrock_llm_provider_complete_returns_text():
    client = MagicMock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": "hello"}]}}
    }
    provider = BedrockLLMProvider(client=client)
    result = provider.complete([{"role": "user", "content": "hi"}])
    assert result == "hello"


@pytest.mark.unit
def test_bedrock_llm_provider_complete_json_appends_json_instruction():
    client = MagicMock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": '{"key": "val"}'}]}}
    }
    provider = BedrockLLMProvider(client=client)
    result = provider.complete_json([{"role": "user", "content": "return json"}])
    assert result == {"key": "val"}

    # Verify that the json_mode_instruction was appended to the system blocks
    call_kwargs = client.converse.call_args.kwargs
    system_blocks = call_kwargs.get("system", [])
    assert any("JSON" in block.get("text", "") for block in system_blocks)


# ── OpenAILLMProvider ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_openai_llm_provider_complete():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello world"
    mock_client.chat.completions.create.return_value = mock_response

    with patch("llm.openai_provider.openai.OpenAI", return_value=mock_client):
        provider = OpenAILLMProvider(api_key="test-key", model="gpt-4o")

    provider.client = mock_client
    result = provider.complete([{"role": "user", "content": "hi"}])
    assert result == "hello world"
    mock_client.chat.completions.create.assert_called_once()


@pytest.mark.unit
def test_openai_llm_provider_complete_returns_empty_string_on_none_content():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = None
    mock_client.chat.completions.create.return_value = mock_response

    with patch("llm.openai_provider.openai.OpenAI", return_value=mock_client):
        provider = OpenAILLMProvider(api_key="test-key")

    provider.client = mock_client
    result = provider.complete([{"role": "user", "content": "hi"}])
    assert result == ""


@pytest.mark.unit
def test_openai_llm_provider_complete_json():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"answer": 42}'
    mock_client.chat.completions.create.return_value = mock_response

    with patch("llm.openai_provider.openai.OpenAI", return_value=mock_client):
        provider = OpenAILLMProvider(api_key="test-key")

    provider.client = mock_client
    result = provider.complete_json([{"role": "user", "content": "json please"}])
    assert result == {"answer": 42}
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.unit
def test_openai_llm_provider_complete_json_returns_empty_dict_on_none():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = None
    mock_client.chat.completions.create.return_value = mock_response

    with patch("llm.openai_provider.openai.OpenAI", return_value=mock_client):
        provider = OpenAILLMProvider(api_key="test-key")

    provider.client = mock_client
    result = provider.complete_json([{"role": "user", "content": "json"}])
    assert result == {}


@pytest.mark.unit
def test_openai_llm_provider_init_uses_api_key():
    with patch("llm.openai_provider.openai.OpenAI") as mock_openai_cls:
        OpenAILLMProvider(api_key="my-key", model="gpt-4o")
        mock_openai_cls.assert_called_once_with(api_key="my-key")
