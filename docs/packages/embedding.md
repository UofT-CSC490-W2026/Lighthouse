# `embedding`

Shared embedding provider package. It gives Lighthouse a small provider interface plus concrete OpenAI and Bedrock implementations.

## What this package contains

- `EmbeddingProvider`: abstract interface with `embed_batch()` and `embed_single()`.
- `OpenAIEmbeddingProvider`: OpenAI embeddings API implementation.
- `BedrockEmbeddingProvider`: AWS Bedrock embedding implementation.
- `EmbeddingStrategy`: provider selector enum with `openai` and `bedrock`.
- `get_embedding_provider()`: registry-based constructor.
- `register_embedding_provider()`: extension hook for custom providers.
- `OPENAI_DEFAULT_EMBEDDING_MODEL`: currently `text-embedding-3-large`.

Exports come from `embedding.__init__`.

## Interface

```python
from embedding import EmbeddingProvider

class MyProvider(EmbeddingProvider):
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        ...
```

`embed_single()` is implemented once in the base class as a convenience wrapper around `embed_batch([text])`.

## OpenAIEmbeddingProvider

OpenAI-backed batch embedder.

### Behavior

- Uses `openai.OpenAI`.
- Defaults to `text-embedding-3-large`.
- Sends requests in batches of `2048` inputs.
- Preserves input order in the returned embeddings.
- Returns `[]` for an empty input list.

### Example

```python
from embedding import OpenAIEmbeddingProvider

provider = OpenAIEmbeddingProvider(api_key="...", model="text-embedding-3-large")
vectors = provider.embed_batch(["hello", "world"])
```

## BedrockEmbeddingProvider

AWS Bedrock-backed embedder for text embedding models.

### Behavior

- Uses `boto3.client("bedrock-runtime")` unless a client is injected.
- Defaults come from `shared.config`:
  - model: `BEDROCK_EMBEDDING_MODEL`
  - dimensions: `BEDROCK_EMBEDDING_DIMENSION`
- Calls `shared.aws.prefer_explicit_aws_credentials()` before building the client.
- Issues one Bedrock request per text.
- Supports optional `normalize`.
- Supports optional `region_name`.

### Token-limit retry behavior

This provider has extra resilience that the OpenAI provider does not:

- If Bedrock returns a token limit error, it shortens the text and retries.
- Truncation keeps the beginning and end of the text with a `\n...\n` marker in the middle.
- Retries are capped.
- If the text still cannot be embedded, it raises `RuntimeError`.

### Example

```python
from embedding import BedrockEmbeddingProvider

provider = BedrockEmbeddingProvider(
    model="amazon.titan-embed-text-v2:0",
    dimensions=1024,
    region_name="us-east-1",
)
vector = provider.embed_single("some code or documentation")
```

## Registry API

The package-level constructor is the normal integration point for services.

```python
from embedding import EmbeddingStrategy, get_embedding_provider

provider = get_embedding_provider(
    EmbeddingStrategy.OPENAI,
    api_key="...",
    model="text-embedding-3-large",
)
```

Supported built-in strategies:

- `EmbeddingStrategy.OPENAI`
- `EmbeddingStrategy.BEDROCK`

You can extend the registry:

```python
from embedding import EmbeddingStrategy, EmbeddingProvider, register_embedding_provider

register_embedding_provider(EmbeddingStrategy.OPENAI, MyCustomProvider)
```

## How Lighthouse uses it

- `services/search` builds the provider from runtime settings.
- `services/ingestion` uses it in Temporal activities for both code chunks and wiki content.
- Provider defaults are coordinated with `shared.config.default_embedding_model()` and `shared.config.default_embedding_dimension()`.

## Configuration expectations

### OpenAI

- `openai_api_key` must be available to the caller when using the OpenAI provider.

### Bedrock

- Standard AWS credentials must be available to boto3.
- If explicit key env vars are present, the package removes conflicting `AWS_PROFILE` settings before client creation.

## Limitations

- No async interface; all provider calls are synchronous.
- No built-in rate limiting or backoff besides Bedrock token-limit retries.
- Only OpenAI and Bedrock are registered by default.
