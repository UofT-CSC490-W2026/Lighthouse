from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from shared.aws import prefer_explicit_aws_credentials


DEFAULT_BASELINE_MODEL = "bedrock/us.amazon.nova-lite-v1:0"
DEFAULT_BASELINE_REGION = "us-east-1"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 4096


class BedrockPatchGenerator:
    def __init__(
        self,
        *,
        model_name: str = DEFAULT_BASELINE_MODEL,
        region_name: str | None = DEFAULT_BASELINE_REGION,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        if not model_name.lower().startswith("bedrock/"):
            raise ValueError(
                f"Unsupported model {model_name!r}. Expected the 'bedrock/<model-id>' format."
            )
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")

        self.model_name = model_name
        self._model_id = model_name.removeprefix("bedrock/")
        self._temperature = temperature
        self._max_tokens = max_tokens

        import boto3

        prefer_explicit_aws_credentials()
        client_kwargs: dict[str, str] = {}
        if region_name:
            client_kwargs["region_name"] = region_name
        self._client = boto3.client("bedrock-runtime", **client_kwargs)

    def generate_text(self, *, system: str, user: str) -> str:
        try:
            response = self._client.converse(
                modelId=self._model_id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={
                    "maxTokens": self._max_tokens,
                    "temperature": self._temperature,
                },
            )
        except Exception as exc:
            message = str(exc)
            if (
                exc.__class__.__name__ == "ValidationException"
                and "model identifier is invalid" in message.lower()
            ):
                raise RuntimeError(
                    "Bedrock rejected the model identifier. This usually means the "
                    "selected region does not support that foundation-model id and "
                    "you should use an inference-profile id instead. Try a model such as "
                    "'bedrock/us.amazon.nova-lite-v1:0' or pass "
                    "--region-name with a supported Bedrock region."
                ) from exc
            raise
        return _extract_text_blocks(response)


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


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}
