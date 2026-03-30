from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any, cast

import httpx

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAIPatchGenerator:
    def __init__(
        self,
        *,
        model_name: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        api_key: str | None = None,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
    ) -> None:
        if not model_name.lower().startswith("openai/"):
            raise ValueError(
                f"Unsupported model {model_name!r}. Expected the 'openai/<model-id>' format."
            )
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")

        resolved_api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not resolved_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for OpenAI generation models (openai/<model-id>)."
            )

        self.model_name = model_name
        self._model_id = model_name.removeprefix("openai/")
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {resolved_api_key}",
                "Content-Type": "application/json",
            },
        )

    def generate_text(self, *, system: str, user: str) -> str:
        response = self._client.post(
            "/chat/completions",
            json={
                "model": self._model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self._temperature,
                "max_completion_tokens": self._max_tokens,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return _extract_text(payload)


def _extract_text(payload: Mapping[str, object]) -> str:
    choices_obj = payload.get("choices")
    if not isinstance(choices_obj, list) or not choices_obj:
        return ""
    first = choices_obj[0]
    if not isinstance(first, Mapping):
        return ""
    message = first.get("message")
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, Mapping):
                continue
            typed_part = cast(Mapping[str, Any], part)
            text = typed_part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
        return "\n".join(text_parts).strip()
    return ""
