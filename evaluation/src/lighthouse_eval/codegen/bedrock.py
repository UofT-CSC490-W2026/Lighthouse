"""AWS Bedrock code generator via the Converse API.

Uses the model-agnostic ``bedrock-runtime.converse`` endpoint so the same
generator works for any model available on Bedrock (Claude, Llama, Mistral,
Titan, etc.).

Model names in configs should use the ``bedrock/<model-id>`` convention::

    models:
      - "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
      - "bedrock/meta.llama3-1-70b-instruct-v1:0"
      - "bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0"

The ``bedrock/`` prefix is stripped before calling the API. AWS credentials
are resolved via the standard boto3 chain (env vars, ~/.aws/credentials,
instance profile, etc.).

Optional config via ``**kwargs`` passed from ``create_generator``:
    region_name: AWS region (default: from boto3 session / env)
    temperature: sampling temperature (default: 0.0)
    max_tokens: max response tokens (default: 4096)
"""

from __future__ import annotations

import asyncio
import logging

from lighthouse_eval.codegen.prompt import build_system_message, build_user_message, parse_response
from lighthouse_eval.context.base import ContextSnippet
from lighthouse_eval.datasets.schema import Task

log = logging.getLogger(__name__)


class BedrockGenerator:
    """Generate candidate edits via AWS Bedrock's Converse API."""

    def __init__(
        self,
        *,
        model_name: str,
        region_name: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> None:
        self.model_name = model_name
        self._model_id = model_name.removeprefix("bedrock/")
        self._temperature = temperature
        self._max_tokens = max_tokens

        import boto3

        session_kwargs: dict = {}
        if region_name:
            session_kwargs["region_name"] = region_name
        self._client = boto3.client("bedrock-runtime", **session_kwargs)

    async def generate(self, task: Task, context: list[ContextSnippet]):
        system = build_system_message(task)
        user = build_user_message(task, context)

        response = await asyncio.to_thread(
            self._client.converse,
            modelId=self._model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={
                "maxTokens": self._max_tokens,
                "temperature": self._temperature,
            },
        )

        raw = ""
        output = response.get("output", {})
        message = output.get("message", {})
        for block in message.get("content", []):
            if "text" in block:
                raw = block["text"]
                break

        return parse_response(raw, task)
