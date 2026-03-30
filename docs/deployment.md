# AWS Deployment Flow

This document describes the current deployment workflow for Lighthouse on AWS.

It covers:

- building and pushing the four runtime images
- loading deployment-only secrets from a local env file
- creating service runtime settings in AWS SSM Parameter Store
- applying Terraform in the required order
- running database migrations
- restarting ECS services with the final runtime configuration

## Current Deployment Model

The current AWS deployment shape is:

- ECS/Fargate for `web`, `mcp_server`, `search`, `ingestion`, and `ingestion-worker`
- RDS PostgreSQL for application data
- one EC2 instance for Milvus plus its local `etcd` and `minio` dependencies
- Temporal Cloud for workflow orchestration
- AWS SSM Parameter Store `SecureString` parameters for per-service runtime config

The deployment entrypoint is:

- [`scripts/deploy_aws_stack.sh`](../scripts/deploy_aws_stack.sh)

The script uses:

- [`scripts/build_and_push_images.sh`](../scripts/build_and_push_images.sh)
- [`scripts/deploy_aws_stack_helper.py`](../scripts/deploy_aws_stack_helper.py)

## Prerequisites

Before running the deployment script, make sure you have:

- Docker installed and working
- the AWS CLI installed and authenticated
- Terraform installed
- permission to create and update:
  - ECR repositories and images
  - ECS services and tasks
  - RDS resources
  - EC2 resources
  - SSM parameters
- GitHub OAuth credentials for the web login flow
- a Temporal Cloud namespace and API key
- an OpenAI API key if you keep the default OpenAI embedding and LLM strategies

## GitHub OAuth Setup

The web login flow goes through the MCP service. The relevant routes are:

- `GET /v1/auth/github`
- `GET /v1/auth/github/callback`

The callback path is implemented in:

- [`services/mcp_server/src/mcp_server/engine/auth.py`](../services/mcp_server/src/mcp_server/engine/auth.py)

The OAuth client settings are consumed from:

- [`services/mcp_server/src/mcp_server/utilities/config/env.py`](../services/mcp_server/src/mcp_server/utilities/config/env.py)

To initialize GitHub OAuth:

1. In GitHub, create an OAuth App.
2. Set the homepage URL to your public web URL.
   Example: `http://<alb-dns-name>/`
3. Set the authorization callback URL to the MCP callback URL served through the ALB.
   Example: `http://<alb-dns-name>/v1/auth/github/callback`
4. Copy the resulting client ID and client secret into `.env.deploy` as:
   - `GITHUB_OAUTH_CLIENT_ID`
   - `GITHUB_OAUTH_CLIENT_SECRET`
5. Run the deploy script. It will write `GITHUB_OAUTH_CALLBACK_URL` into the MCP SSM payload using the deployed ALB hostname.

The GitHub scopes requested by the app are currently:

- `read:user`
- `read:org`
- `repo`

## Local Deployment Env File

Use a local, untracked env file for deployment-only inputs:

1. copy the template:

```bash
cp .env.deploy.example .env.deploy
```

2. fill in the real values in `.env.deploy`
3. run the deploy script from the repo root

The real `.env.deploy` file is ignored by git. The example file is:

- [`.env.deploy.example`](../.env.deploy.example)

The deploy script auto-loads `.env.deploy` by default. You can override that with:

```bash
ENV_FILE=.env.deploy.prod ./scripts/deploy_aws_stack.sh
```

## Deployment Env Reference

These variables are read by [`scripts/deploy_aws_stack.sh`](../scripts/deploy_aws_stack.sh). Some control the
deployment itself, and others are converted into SSM runtime settings for MCP, Search, and Ingestion.

### Core Secrets And External Services

| Variable | Required | Default | Valid values | Description |
| --- | --- | --- | --- | --- |
| `DB_PASSWORD` | Yes | None | Any PostgreSQL password string | Password used when constructing the application `POSTGRES_DSN` written into SSM and passed to Terraform. |
| `GITHUB_OAUTH_CLIENT_ID` | Yes | None | GitHub OAuth app client ID | GitHub OAuth client ID used by the MCP auth flow. |
| `GITHUB_OAUTH_CLIENT_SECRET` | Yes | None | GitHub OAuth app client secret | GitHub OAuth client secret used by the MCP auth flow. |
| `TEMPORAL_ADDRESS` | Yes | None | Temporal Cloud endpoint, usually `<namespace>.tmprl.cloud:7233` | Host and port for the external Temporal Cloud frontend. |
| `TEMPORAL_NAMESPACE` | Yes | None | Your Temporal Cloud namespace string | Namespace used when ingestion connects to Temporal Cloud. |
| `TEMPORAL_API_KEY` | Yes | None | Temporal Cloud API key | API key used for Temporal Cloud authentication. |
| `OPENAI_API_KEY` | Conditionally | None | OpenAI API key | Required whenever the chosen deployment uses OpenAI-backed embedding or LLM settings. |
| `COHERE_API_KEY` | Conditionally | Empty | Cohere API key | Needed in practice for Search reranking and LLM-combined search flows that use the Cohere reranker. |
| `GITHUB_WEBHOOK_SECRET` | Yes | None | Any shared secret string | Secret written into ingestion settings for GitHub webhook verification. It must match the webhook or GitHub App configuration that sends events to this deployment. |
| `SESSION_ENCRYPTION_KEY` | Yes | None | Fernet-compatible base64 key | Key used by MCP to encrypt session tokens and persisted credentials. Keep it stable for the lifetime of an environment; rotating it invalidates previously encrypted values. |
| `INTERNAL_SERVICE_TOKEN` | Yes | None | Any shared bearer token | Internal auth token shared across MCP, Search, and Ingestion. Keep it stable for the environment so all services continue to trust each other across redeploys. |
| `KMS_KEY_ID` | No | AWS managed SSM key | KMS key ID or ARN | Optional KMS key used when writing SecureString SSM parameters. |

### Deployment And Naming Controls

| Variable | Required | Default | Valid values | Description |
| --- | --- | --- | --- | --- |
| `REGION` | No | `aws_region` from [`infra/terraform.tfvars`](../infra/terraform.tfvars) | Any AWS region string | AWS region used for ECR, ECS, SSM, and Terraform apply operations. |
| `ACCOUNT_ID` | No | `aws sts get-caller-identity` result | AWS account ID | Override for ECR image URI generation. |
| `TAG` | No | `latest` | Any Docker tag string | Tag applied to all four pushed images. |
| `AUTO_APPROVE` | No | `0` | `0` or `1` | When `1`, the deploy script passes `-auto-approve` to Terraform apply. |
| `PROJECT_NAME` | No | `project_name` from tfvars | Any DNS-safe project slug | Prefix used in ECR repo names, SSM parameter names, and other generated identifiers. |
| `ENVIRONMENT` | No | `environment` from tfvars | Any environment slug such as `dev`, `staging`, `prod` | Environment suffix used in generated resource names. |
| `DB_NAME` | No | `db_name` from tfvars | Any PostgreSQL database name | Database name inserted into the application DSN. |
| `DB_USERNAME` | No | `db_username` from tfvars | Any PostgreSQL username | Database username inserted into the application DSN. |
| `PRIVATE_DNS_NAMESPACE_NAME` | No | `${PROJECT_NAME}-${ENVIRONMENT}.local` | Any private DNS namespace | Cloud Map namespace used for service-to-service URLs such as `search.<namespace>`. |
| `MCP_SSM_NAME` | No | `/${PROJECT_NAME}/${ENVIRONMENT}/mcp-server` | Any SSM parameter path | Name of the MCP SecureString parameter. |
| `SEARCH_SSM_NAME` | No | `/${PROJECT_NAME}/${ENVIRONMENT}/search` | Any SSM parameter path | Name of the Search SecureString parameter. |
| `INGESTION_SSM_NAME` | No | `/${PROJECT_NAME}/${ENVIRONMENT}/ingestion` | Any SSM parameter path | Name of the Ingestion SecureString parameter. |
| `WEB_REPO` | No | `${PROJECT_NAME}-${ENVIRONMENT}-web` | Any ECR repository name | ECR repository used for the web image. |
| `MCP_REPO` | No | `${PROJECT_NAME}-${ENVIRONMENT}-mcp` | Any ECR repository name | ECR repository used for the MCP image. |
| `SEARCH_REPO` | No | `${PROJECT_NAME}-${ENVIRONMENT}-search` | Any ECR repository name | ECR repository used for the search image. |
| `INGEST_REPO` | No | `${PROJECT_NAME}-${ENVIRONMENT}-ingestion` | Any ECR repository name | ECR repository used for the ingestion image. |

### Shared Runtime Defaults

These are convenience defaults. Service-specific overrides below take precedence.

| Variable | Required | Default | Valid values | Description |
| --- | --- | --- | --- | --- |
| `EMBEDDING_STRATEGY` | No | `openai` | `openai`, `bedrock` | Shared default used for Search and Ingestion embedding strategy when a service-specific override is not set. |
| `LLM_STRATEGY` | No | `openai` | `openai`, `bedrock` | Shared default used for Ingestion LLM strategy when `INGESTION_LLM_STRATEGY` is not set. |

### MCP Runtime Settings

| Variable | Required | Default | Valid values | Description |
| --- | --- | --- | --- | --- |
| `MCP_DEBUG` | No | `false` | `true`, `false` | Controls MCP debug mode and secure cookie behavior. |
| `SESSION_TTL_HOURS` | No | `168` | Positive integer hours | Lifetime of issued Lighthouse session/API tokens. |

### Search Runtime Settings

| Variable | Required | Default | Valid values | Description |
| --- | --- | --- | --- | --- |
| `SEARCH_EMBEDDING_STRATEGY` | No | `EMBEDDING_STRATEGY` | `openai`, `bedrock` | Embedding provider used by Search for code and wiki vector queries. |
| `SEARCH_EMBEDDING_MODEL` | No | Empty, so the service resolves its provider default | For `openai`: typically `text-embedding-3-large`; for `bedrock`: typically `amazon.titan-embed-text-v2:0` | Explicit embedding model override for Search. Leave blank to use the service default for the chosen strategy. |
| `SEARCH_RERANK_MODEL` | No | `rerank-v4.0-pro` | Cohere rerank model string | Reranker model passed to the Cohere reranker used by Search. |
| `SEARCH_LLM_MODEL` | No | `gpt-5.4-nano` | OpenAI chat model string | Model used by Search's LLM-combined search path. Search currently instantiates an OpenAI LLM provider regardless of embedding strategy. |
| `SEARCH_LLM_REASONING_EFFORT` | No | `none` | Free-form provider string; commonly `none`, `low`, `medium`, `high` | Reasoning effort forwarded to Search's LLM-combined path. |

### Ingestion Runtime Settings

| Variable | Required | Default | Valid values | Description |
| --- | --- | --- | --- | --- |
| `TEMPORAL_TASK_QUEUE` | No | `ingestion` | Any Temporal task queue name | Task queue polled by the ingestion worker. |
| `CHUNKER_STRATEGY` | No | `ast_code` | `sliding_window`, `ast_code` | Chunking strategy used when ingestion splits repository files before embedding. |
| `INGESTION_CLONE_BASE_DIR` | No | `/tmp/lighthouse_repos` | Writable filesystem path | Local directory used by ingestion to clone repositories and stage files. |
| `INGESTION_EMBEDDING_STRATEGY` | No | `EMBEDDING_STRATEGY` | `openai`, `bedrock` | Embedding provider used by ingestion activities. |
| `INGESTION_EMBEDDING_MODEL` | No | Empty, so the service resolves its provider default | For `openai`: typically `text-embedding-3-large`; for `bedrock`: typically `amazon.titan-embed-text-v2:0` | Explicit ingestion embedding model override. |
| `INGESTION_EMBEDDING_DIMENSION` | No | `0` | Positive integer; typically `3072` for OpenAI or `1024` for Bedrock Titan | Vector dimension override for ingestion embeddings. `0` means let the app infer the dimension from the strategy. |
| `INGESTION_LLM_STRATEGY` | No | `LLM_STRATEGY` | `openai`, `bedrock` | LLM provider used by ingestion wiki-generation and related workflows. |
| `INGESTION_LLM_MODEL` | No | Empty, so the service resolves its provider default | For `openai`: typically `gpt-5.4-mini`; for `bedrock`: typically `us.amazon.nova-lite-v1:0` | Explicit ingestion LLM model override. |
| `INGESTION_LLM_REASONING_EFFORT` | No | Empty, so the app uses its strategy-specific default | Free-form provider string; commonly `low`, `medium`, `high` for OpenAI, empty for Bedrock | Reasoning effort forwarded to ingestion wiki-generation calls when supported by the selected LLM provider. |

## What the Deploy Script Does

The end-to-end flow is:

1. load `.env.deploy` if present
2. resolve defaults from [`infra/terraform.tfvars`](../infra/terraform.tfvars)
3. build and push four Docker images to ECR:
   - `web`
   - `mcp`
   - `search`
   - `ingestion`
4. generate a temporary Terraform var overlay with:
   - the pushed image URIs
   - the SSM parameter names and ARNs
   - the database password
5. run a targeted Terraform apply to create enough infrastructure to discover:
   - the RDS endpoint
   - the ALB URL
   - the Milvus EC2 private IP
   - the ECS cluster and migration task definition
6. generate three SSM `SecureString` JSON payloads:
   - MCP settings
   - Search settings
   - Ingestion settings
7. write or update those SSM parameters
8. run the one-off ECS migration task
9. run the full Terraform apply
10. force fresh ECS deployments so the services reload the final SSM config
11. wait for the ECS services to become stable

## SSM Parameters

The deployment uses one JSON SSM parameter per service:

- MCP
- Search
- Ingestion

The parameter names default to:

- `/${project_name}/${environment}/mcp-server`
- `/${project_name}/${environment}/search`
- `/${project_name}/${environment}/ingestion`

These names can be overridden from the env file using:

- `MCP_SSM_NAME`
- `SEARCH_SSM_NAME`
- `INGESTION_SSM_NAME`

The runtime settings schemas come from:

- [`services/mcp_server/src/mcp_server/utilities/config/env.py`](../services/mcp_server/src/mcp_server/utilities/config/env.py)
- [`services/search/src/search/config.py`](../services/search/src/search/config.py)
- [`services/ingestion/src/ingestion/utilities/config.py`](../services/ingestion/src/ingestion/utilities/config.py)

Use `.env.deploy` for these deployment-time runtime choices. The deploy script writes them into the per-service
SSM payloads. They should not be stored in tracked Terraform files.

The deploy script does not auto-generate persistent secrets anymore. Set these explicitly in `.env.deploy` before the
first deployment and keep them stable for the life of the environment:

- `SESSION_ENCRYPTION_KEY`
- `INTERNAL_SERVICE_TOKEN`
- `GITHUB_WEBHOOK_SECRET`

Example one-time generation commands:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # SESSION_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_hex(32))"  # INTERNAL_SERVICE_TOKEN or GITHUB_WEBHOOK_SECRET
```

Important runtime values populated by the script:

- `POSTGRES_DSN`
- `MILVUS_URI`
- `SEARCH_SERVICE_URL`
- `INGESTION_SERVICE_URL`
- `INTERNAL_SERVICE_TOKEN`
- `TEMPORAL_ADDRESS`
- `TEMPORAL_NAMESPACE`
- `TEMPORAL_API_KEY`
- search embedding, rerank, and LLM model settings
- ingestion embedding, embedding dimension, LLM, and clone path settings

`INTERNAL_SERVICE_TOKEN` must match across MCP, Search, and Ingestion.

The env file supports two levels of overrides:

- shared defaults such as `EMBEDDING_STRATEGY` and `LLM_STRATEGY`
- service-specific overrides such as `SEARCH_EMBEDDING_MODEL` or `INGESTION_LLM_MODEL`

If a service-specific override is not set, the deploy script falls back to the shared setting or the service's own
runtime default where appropriate.

## Temporal Cloud

Lighthouse no longer provisions a self-hosted Temporal server in AWS.

Instead, ingestion connects to Temporal Cloud using:

- `TEMPORAL_ADDRESS`
- `TEMPORAL_NAMESPACE`
- `TEMPORAL_API_KEY`

The ingestion service already supports this configuration. See:

- [`services/ingestion/src/ingestion/utilities/config.py`](../services/ingestion/src/ingestion/utilities/config.py)

TLS is enabled automatically for Temporal Cloud targets.

## Running the Deployment

Typical flow:

```bash
cp .env.deploy.example .env.deploy
$EDITOR .env.deploy
TAG=$(git rev-parse --short HEAD) AUTO_APPROVE=1 ./scripts/deploy_aws_stack.sh
```

If you want to review the Terraform steps manually, leave `AUTO_APPROVE=0`.

## Smoke Tests

After a successful run, test:

```bash
curl http://<alb-dns-name>/
curl http://<alb-dns-name>/health
```

Then verify end-to-end behavior:

- log into the web app
- add a repository from the UI
- confirm indexing starts
- confirm the ingestion worker connects to Temporal Cloud
- run search through the UI or MCP
- generate and search wiki content

## Known Notes

- The deploy script is meant for real AWS deployment, not for local Docker Compose development.
- Local development still uses `docker-compose.yml`.
- The script writes runtime config to SSM, not to tracked Terraform files.
- [`infra/terraform.tfvars`](../infra/terraform.tfvars) is gitignored and should not hold real secrets in source control.

## Auth State Recovery

If `SESSION_ENCRYPTION_KEY` was accidentally changed and MCP starts failing with `cryptography.fernet.InvalidToken`,
do not try to fix that through Terraform. Restore a stable `SESSION_ENCRYPTION_KEY`, then reset only the auth state
with:

```bash
POSTGRES_DSN='postgresql://...' ./scripts/reset_auth_state.sh
```

Use `--dry-run` first if you want to see how many rows will be affected.

If RDS is private and your laptop cannot reach it, run the same reset inside AWS with:

```bash
./scripts/reset_auth_state_aws.sh --dry-run
./scripts/reset_auth_state_aws.sh
```

That helper reuses the existing `db-migrate` ECS task definition so the reset runs from inside the VPC.
