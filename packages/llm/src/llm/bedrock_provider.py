from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

import boto3
from shared.aws import prefer_explicit_aws_credentials
from shared.config import BEDROCK_LLM_MODEL

from .base_provider import LLMProvider


class BedrockLLMProvider(LLMProvider):
    """LLM provider backed by AWS Bedrock's Converse API."""

    def __init__(
        self,
        *,
        model: str = BEDROCK_LLM_MODEL,
        region_name: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        if client is None:
            prefer_explicit_aws_credentials()
            client_kwargs: dict[str, str] = {}
            if region_name:
                client_kwargs["region_name"] = region_name
            client = boto3.client("bedrock-runtime", **client_kwargs)
        self.client = client

    def complete(self, messages: list[dict[str, str]], **kwargs) -> str:
        response = self.client.converse(
            modelId=self.model,
            **_build_bedrock_message_payload(messages),
            **kwargs,
        )
        return _extract_text_blocks(response)

    def complete_json(self, messages: list[dict[str, str]], **kwargs) -> dict:
        response = self.client.converse(
            modelId=self.model,
            **_build_bedrock_message_payload(
                messages,
                json_mode_instruction=(
                    "Return only a valid JSON object that matches the requested schema."
                ),
            ),
            **kwargs,
        )
        return _parse_json_response(_extract_text_blocks(response))


def _build_bedrock_message_payload(
    messages: list[dict[str, str]],
    *,
    json_mode_instruction: str | None = None,
) -> dict[str, object]:
    system_blocks: list[dict[str, str]] = []
    bedrock_messages: list[dict[str, object]] = []

    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", ""))
        if not content:
            continue
        if role == "system":
            system_blocks.append({"text": content})
            continue

        normalized_role = "assistant" if role == "assistant" else "user"
        bedrock_messages.append(
            {
                "role": normalized_role,
                "content": [{"text": content}],
            }
        )

    if json_mode_instruction:
        system_blocks.append({"text": json_mode_instruction})

    payload: dict[str, object] = {"messages": bedrock_messages}
    if system_blocks:
        payload["system"] = system_blocks
    return payload


def _extract_text_blocks(response: Mapping[str, object]) -> str:
    output = _as_mapping(response.get("output"))
    message = _as_mapping(output.get("message"))
    content = message.get("content")
    if not isinstance(content, list):
        return ""

    blocks: list[str] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        typed_block = cast(Mapping[str, object], block)
        text = typed_block.get("text")
        if isinstance(text, str) and text.strip():
            blocks.append(text)
    return "\n".join(blocks).strip()


def _parse_json_response(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        return {}

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("Bedrock JSON completion did not return a JSON object.")
    return parsed


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}
