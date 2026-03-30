# `shared`

Cross-service utilities and schemas used by the Lighthouse Python services. This package holds the stable contracts that multiple services depend on: config constants, auth helpers, SSM settings loading, and API request/response models.

## What this package contains

- Config constants and strategy defaults in `shared.config`
- Internal service auth helper in `shared.auth`
- AWS credential normalization helper in `shared.aws`
- Pydantic settings source for AWS SSM in `shared.ssm`
- Shared API schemas in `shared.schemas`

Package-level exports from `shared.__init__` are intentionally small:

- `SSMSettingsSource`
- `ssm_settings_sources`
- `verify_internal_token`
- `prefer_explicit_aws_credentials`

## `shared.config`

Central constants used across ingestion and search.

### Strategy defaults

- `DEFAULT_EMBEDDING_STRATEGY = "openai"`
- `DEFAULT_LLM_STRATEGY = "bedrock"`

### Model defaults

- `BEDROCK_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"`
- `BEDROCK_EMBEDDING_DIMENSION = 1024`
- `OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"`
- `OPENAI_EMBEDDING_DIMENSION = 3072`
- `BEDROCK_LLM_MODEL = "us.amazon.nova-lite-v1:0"`
- `OPENAI_LLM_MODEL = "gpt-5.4-nano"`
- `OPENAI_REASONING_EFFORT = "none"`

### Retrieval and chunking constants

- `MILVUS_COLLECTION_NAME = "chunk_embeddings"`
- `WIKI_MILVUS_COLLECTION_NAME = "wiki_embeddings"`
- `CHUNK_MAX_LINES = 50`
- `CHUNK_OVERLAP_LINES = 10`

### Helper functions

- `default_embedding_model(strategy: str) -> str`
- `default_embedding_dimension(strategy: str) -> int`
- `default_llm_model(strategy: str) -> str`

These normalize the strategy name and raise `ValueError` for unsupported strategies.

## `shared.auth`

`verify_internal_token()` is the FastAPI dependency used to protect internal service endpoints.

### Contract

- Reads the expected token from `request.app.state.settings.internal_service_token`.
- If the configured token is empty, validation is skipped. This supports local development.
- Otherwise it expects `Authorization: Bearer <token>`.
- Uses `secrets.compare_digest()` for constant-time comparison.
- Raises `HTTPException(status_code=401)` on missing, malformed, or invalid tokens.

### Example

```python
from fastapi import Depends
from shared.auth import verify_internal_token

@app.post("/internal", dependencies=[Depends(verify_internal_token)])
async def internal_endpoint() -> dict[str, str]:
    return {"status": "ok"}
```

## `shared.aws`

`prefer_explicit_aws_credentials()` avoids a common local-container failure mode:

- if `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are both set,
- it removes `AWS_PROFILE` and `AWS_DEFAULT_PROFILE`
- so boto3 prefers the explicit key material instead of failing on a stray profile reference.

Both the Bedrock LLM and embedding packages use this before creating boto3 clients.

## `shared.ssm`

This module adds AWS SSM Parameter Store as an optional Pydantic settings source.

### Design

- Services store settings in one encrypted SSM parameter containing a JSON object.
- The parameter name itself is supplied by an environment variable.
- If that environment variable is unset or empty, the source becomes a no-op.
- Source ordering is:
  - init args
  - environment variables
  - `.env`
  - file secrets
  - SSM

That means SSM acts as a fallback, not an override.

### Main APIs

- `SSMSettingsSource(settings_cls, ssm_env_var)`
- `ssm_settings_sources(ssm_env_var, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings)`
- `get_ssm_client(region_name=None)`

### Region resolution

The SSM helper resolves region from:

- `AWS_REGION`
- `AWS_DEFAULT_REGION`

### Example

```python
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from shared.ssm import ssm_settings_sources

class Settings(BaseSettings):
    api_key: str = ""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return ssm_settings_sources(
            "MY_SERVICE_SETTINGS_SSM_PARAMETER",
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
```

## `shared.schemas`

Pydantic models shared between services.

### Ingestion schemas

From `shared.schemas.ingestion`:

- `RepoIndexRequest`
- `IndexRequest`
- `IndexAcceptedResponse`
- `BranchStatus`
- `IndexStatusResponse`

These define the payloads for ingestion requests and branch status responses.

### Search schemas

From `shared.schemas.search`:

- `SearchMethod`
- `SearchContextSource`
- `SearchRequest`
- `HybridRequest`
- `CodeSnippet`
- `SearchResult`
- `WikiSearchRequest`
- `WikiSnippet`
- `WikiSearchResult`
- `CombinedSnippet`
- `CombinedSearchResult`

Notable behavior:

- `SearchRequest.top_k` is constrained to `1..100`.
- `WikiSearchRequest.top_k` defaults to `5` and is constrained to `1..50`.
- `SearchRequest.requested_context_sources()` deduplicates `context_sources` while preserving order.

### Wiki schemas

From `shared.schemas.wiki`:

- `WikiStructurePage`
- `WikiStructureSection`
- `WikiStructure`
- `GenerateWikiRequest`
- `GenerateWikiAcceptedResponse`
- `WikiPageResponse`
- `WikiStatusResponse`
- `WikiResponse`

These models cover wiki outline generation, accepted workflow responses, status polling, and final wiki payloads.

## How Lighthouse uses it

- `services/search` uses `shared.config`, `shared.auth`, `shared.ssm`, and search schemas heavily.
- `services/ingestion` uses `shared.config`, `shared.auth`, `shared.ssm`, ingestion schemas, and wiki schemas.
- `services/mcp_server` uses the same schema package to call search and ingestion consistently.

## Scope boundary

`shared` is intentionally infrastructure-light. It does not contain service-specific workflows, database models, or external API clients beyond settings/auth helpers.
