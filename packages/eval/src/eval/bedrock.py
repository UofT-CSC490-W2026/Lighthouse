from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import cast

from shared.aws import prefer_explicit_aws_credentials
from eval.generator import GenerationResult


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

    def generate(self, *, system: str, user: str) -> GenerationResult:
        started = perf_counter()
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
        latency_ms = (perf_counter() - started) * 1000.0
        text = _extract_text_blocks(response)
        usage = _extract_usage(response)
        return GenerationResult(
            text=text,
            input_tokens=usage[0],
            output_tokens=usage[1],
            total_tokens=usage[2],
            latency_ms=usage[3] if usage[3] > 0 else latency_ms,
        )

    def generate_text(self, *, system: str, user: str) -> str:
        return self.generate(system=system, user=user).text


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


def _extract_usage(response: Mapping[str, object]) -> tuple[int, int, int, float]:
    usage = _as_mapping(response.get("usage"))
    input_tokens = int(usage.get("inputTokens", 0) or 0)
    output_tokens = int(usage.get("outputTokens", 0) or 0)
    total_tokens = int(usage.get("totalTokens", input_tokens + output_tokens) or 0)
    metrics = _as_mapping(response.get("metrics"))
    latency_ms = float(metrics.get("latencyMs", 0.0) or 0.0)
    return input_tokens, output_tokens, total_tokens, latency_ms
