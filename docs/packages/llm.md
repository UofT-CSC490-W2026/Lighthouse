# `llm`

Shared large language model provider package. It defines a minimal completion interface and concrete OpenAI and Bedrock implementations used by Lighthouse services.

## What this package contains

- `LLMProvider`: abstract interface.
- `OpenAILLMProvider`: OpenAI chat-completions implementation.
- `BedrockLLMProvider`: AWS Bedrock Converse API implementation.

These are re-exported from `llm.__init__`.

## Interface

`LLMProvider` defines two operations:

- `complete(messages, **kwargs) -> str`
- `complete_json(messages, **kwargs) -> dict`

The message shape is the standard Lighthouse chat format:

```python
[
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Summarize this repository."},
]
```

## OpenAILLMProvider

OpenAI-backed implementation using `openai.OpenAI().chat.completions.create(...)`.

### Behavior

- Requires an explicit `api_key` in the constructor.
- Defaults the model from `shared.config.LLM_MODEL`.
- `complete()` returns the first choice's message content, or `""` if the API returns `None`.
- `complete_json()` requests `response_format={"type": "json_object"}` and parses the returned JSON.
- If the response content is empty in JSON mode, it returns `{}`.

### Example

```python
from llm import OpenAILLMProvider

provider = OpenAILLMProvider(api_key="...", model="gpt-5.4-nano")
text = provider.complete([{"role": "user", "content": "Explain this function."}])
data = provider.complete_json([{"role": "user", "content": "Return JSON only."}])
```

## BedrockLLMProvider

Bedrock-backed implementation using the Converse API.

### Behavior

- Uses `boto3.client("bedrock-runtime")` unless a client is injected.
- Defaults the model from `shared.config.BEDROCK_LLM_MODEL`.
- Calls `shared.aws.prefer_explicit_aws_credentials()` before building the client.
- Converts Lighthouse chat messages into Bedrock's `system` and `messages` payload structure.
- Ignores empty message content.
- Normalizes non-system roles to `user`, except `assistant` which stays `assistant`.

### JSON mode behavior

`complete_json()` adds an extra system instruction asking the model to return only a valid JSON object, then:

- extracts concatenated text blocks from the Bedrock response,
- parses the result as JSON,
- falls back to extracting the first outer `{...}` object if the response contains surrounding prose,
- raises if the parsed value is not a JSON object.

### Example

```python
from llm import BedrockLLMProvider

provider = BedrockLLMProvider(model="us.amazon.nova-lite-v1:0", region_name="us-east-1")
summary = provider.complete([{"role": "user", "content": "Summarize the repo."}])
metadata = provider.complete_json([{"role": "user", "content": "Return a JSON object."}])
```

## Registry note

Unlike `embedding`, this package does not expose a built-in registry. Lighthouse's ingestion service defines its own `LLMStrategy` registry in `services/ingestion/src/ingestion/llm/registry.py` on top of these provider classes.

## How Lighthouse uses it

- `services/search` currently constructs `OpenAILLMProvider` directly for LLM-combined search.
- `services/ingestion` uses both OpenAI and Bedrock through its service-local registry layer for wiki generation.

## Configuration expectations

### OpenAI

- Caller must supply `api_key`.
- The default model constant currently points to `gpt-5.4-nano` through `shared.config`.

### Bedrock

- Standard boto3 credential resolution applies.
- If explicit key env vars are present, conflicting profile env vars are cleared before client construction.

## Limitations

- Synchronous API only.
- No streaming support.
- No retry, backoff, or tool-calling abstraction in this package.
