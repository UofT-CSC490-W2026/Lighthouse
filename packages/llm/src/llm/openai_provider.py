from __future__ import annotations

import json

import openai
from shared.config import LLM_MODEL

from .base_provider import LLMProvider


class OpenAILLMProvider(LLMProvider):
    """LLM provider backed by the OpenAI chat completions API."""

    def __init__(self, api_key: str, model: str = LLM_MODEL) -> None:
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def complete(self, messages: list[dict[str, str]], **kwargs) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    def complete_json(self, messages: list[dict[str, str]], **kwargs) -> dict:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            **kwargs,
        )
        return json.loads(response.choices[0].message.content or "{}")
