#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required" >&2
    exit 1
  fi
}

require_cmd aws
require_cmd docker
require_cmd terraform
require_cmd python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${REPO_ROOT}/infra"
BASE_TFVARS="${TFVARS_PATH:-${INFRA_DIR}/terraform.tfvars}"

if [[ ! -f "$BASE_TFVARS" ]]; then
  echo "Terraform var file not found: $BASE_TFVARS" >&2
  exit 1
fi

read_tfvar_string() {
  local key="$1"
  python3 - "$BASE_TFVARS" "$key" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
key = sys.argv[2]
text = path.read_text()
pattern = re.compile(rf"^{re.escape(key)}\s*=\s*\"([^\"]*)\"", re.MULTILINE)
match = pattern.search(text)
if not match:
    raise SystemExit(1)
print(match.group(1))
PY
}

PROJECT_NAME="${PROJECT_NAME:-$(read_tfvar_string project_name)}"
ENVIRONMENT="${ENVIRONMENT:-$(read_tfvar_string environment)}"
REGION="${REGION:-$(read_tfvar_string aws_region)}"
DB_NAME="${DB_NAME:-$(read_tfvar_string db_name)}"
DB_USERNAME="${DB_USERNAME:-$(read_tfvar_string db_username)}"

ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
TAG="${TAG:-latest}"
PRIVATE_DNS_NAMESPACE_NAME="${PRIVATE_DNS_NAMESPACE_NAME:-${PROJECT_NAME}-${ENVIRONMENT}.local}"

WEB_REPO="${WEB_REPO:-${PROJECT_NAME}-${ENVIRONMENT}-web}"
MCP_REPO="${MCP_REPO:-${PROJECT_NAME}-${ENVIRONMENT}-mcp}"
SEARCH_REPO="${SEARCH_REPO:-${PROJECT_NAME}-${ENVIRONMENT}-search}"
INGEST_REPO="${INGEST_REPO:-${PROJECT_NAME}-${ENVIRONMENT}-ingestion}"

WEB_IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${WEB_REPO}:${TAG}"
MCP_IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${MCP_REPO}:${TAG}"
SEARCH_IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${SEARCH_REPO}:${TAG}"
INGESTION_IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${INGEST_REPO}:${TAG}"

MCP_SSM_NAME="${MCP_SSM_NAME:-/${PROJECT_NAME}/${ENVIRONMENT}/mcp-server}"
SEARCH_SSM_NAME="${SEARCH_SSM_NAME:-/${PROJECT_NAME}/${ENVIRONMENT}/search}"
INGESTION_SSM_NAME="${INGESTION_SSM_NAME:-/${PROJECT_NAME}/${ENVIRONMENT}/ingestion}"

MCP_SSM_ARN="arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter${MCP_SSM_NAME}"
SEARCH_SSM_ARN="arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter${SEARCH_SSM_NAME}"
INGESTION_SSM_ARN="arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter${INGESTION_SSM_NAME}"

SESSION_ENCRYPTION_KEY="${SESSION_ENCRYPTION_KEY:-$(python3 - <<'PY'
import base64
import os
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
)}"
INTERNAL_SERVICE_TOKEN="${INTERNAL_SERVICE_TOKEN:-$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)}"
GITHUB_WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET:-$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)}"

EMBEDDING_STRATEGY="${EMBEDDING_STRATEGY:-openai}"
LLM_STRATEGY="${LLM_STRATEGY:-openai}"
COHERE_API_KEY="${COHERE_API_KEY:-}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
MCP_DEBUG="${MCP_DEBUG:-false}"
SESSION_TTL_HOURS="${SESSION_TTL_HOURS:-168}"
TEMPORAL_TASK_QUEUE="${TEMPORAL_TASK_QUEUE:-ingestion}"
CHUNKER_STRATEGY="${CHUNKER_STRATEGY:-sliding_window}"

DB_PASSWORD="${DB_PASSWORD:-}"
GITHUB_OAUTH_CLIENT_ID="${GITHUB_OAUTH_CLIENT_ID:-}"
GITHUB_OAUTH_CLIENT_SECRET="${GITHUB_OAUTH_CLIENT_SECRET:-}"
KMS_KEY_ID="${KMS_KEY_ID:-}"

if [[ -z "$DB_PASSWORD" ]]; then
  echo "DB_PASSWORD must be set" >&2
  exit 1
fi

if [[ -z "$GITHUB_OAUTH_CLIENT_ID" || -z "$GITHUB_OAUTH_CLIENT_SECRET" ]]; then
  echo "GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET must be set" >&2
  exit 1
fi

if [[ "$EMBEDDING_STRATEGY" == "openai" || "$LLM_STRATEGY" == "openai" ]]; then
  if [[ -z "$OPENAI_API_KEY" ]]; then
    echo "OPENAI_API_KEY must be set when EMBEDDING_STRATEGY or LLM_STRATEGY uses openai" >&2
    exit 1
  fi
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

GENERATED_TFVARS="${TMP_DIR}/generated.auto.tfvars.json"
MCP_SSM_JSON="${TMP_DIR}/mcp-settings.json"
SEARCH_SSM_JSON="${TMP_DIR}/search-settings.json"
INGESTION_SSM_JSON="${TMP_DIR}/ingestion-settings.json"

export GENERATED_TFVARS WEB_IMAGE MCP_IMAGE SEARCH_IMAGE INGESTION_IMAGE
export MCP_SSM_NAME MCP_SSM_ARN SEARCH_SSM_NAME SEARCH_SSM_ARN
export INGESTION_SSM_NAME INGESTION_SSM_ARN DB_PASSWORD

python3 - <<'PY'
import json
import os

payload = {
    "web_image": os.environ["WEB_IMAGE"],
    "mcp_image": os.environ["MCP_IMAGE"],
    "search_image": os.environ["SEARCH_IMAGE"],
    "ingestion_image": os.environ["INGESTION_IMAGE"],
    "mcp_server_settings_ssm_parameter_name": os.environ["MCP_SSM_NAME"],
    "mcp_server_settings_ssm_parameter_arn": os.environ["MCP_SSM_ARN"],
    "search_settings_ssm_parameter_name": os.environ["SEARCH_SSM_NAME"],
    "search_settings_ssm_parameter_arn": os.environ["SEARCH_SSM_ARN"],
    "ingestion_settings_ssm_parameter_name": os.environ["INGESTION_SSM_NAME"],
    "ingestion_settings_ssm_parameter_arn": os.environ["INGESTION_SSM_ARN"],
    "db_password": os.environ["DB_PASSWORD"],
}

with open(os.environ["GENERATED_TFVARS"], "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY

terraform_apply() {
  local auto_approve_flag=()
  if [[ "${AUTO_APPROVE:-0}" == "1" ]]; then
    auto_approve_flag=(-auto-approve)
  fi

  terraform -chdir="$INFRA_DIR" apply \
    -input=false \
    "${auto_approve_flag[@]}" \
    -var-file="$BASE_TFVARS" \
    -var-file="$GENERATED_TFVARS" \
    "$@"
}

put_ssm_parameter() {
  local name="$1"
  local file="$2"
  local args=(
    aws ssm put-parameter
    --name "$name"
    --type SecureString
    --value "file://${file}"
    --overwrite
    --region "$REGION"
  )

  if [[ -n "$KMS_KEY_ID" ]]; then
    args+=(--key-id "$KMS_KEY_ID")
  fi

  "${args[@]}" >/dev/null
}

write_ssm_payloads() {
  local db_endpoint="$1"
  local web_url="$2"
  local mcp_base_url="$3"
  local temporal_private_ip="$4"
  local milvus_private_ip="$5"

  local postgres_dsn="postgresql://${DB_USERNAME}:${DB_PASSWORD}@${db_endpoint}/${DB_NAME}"
  local search_service_url="http://search.${PRIVATE_DNS_NAMESPACE_NAME}:8002"
  local ingestion_service_url="http://ingestion.${PRIVATE_DNS_NAMESPACE_NAME}:8001"
  local temporal_address="${temporal_private_ip}:7233"
  local milvus_uri="http://${milvus_private_ip}:19530"
  local github_callback_url="${mcp_base_url}/v1/auth/github/callback"

  export MCP_SSM_JSON SEARCH_SSM_JSON INGESTION_SSM_JSON
  export MCP_DEBUG web_url postgres_dsn GITHUB_OAUTH_CLIENT_ID GITHUB_OAUTH_CLIENT_SECRET
  export github_callback_url SESSION_ENCRYPTION_KEY SESSION_TTL_HOURS REGION
  export search_service_url ingestion_service_url INTERNAL_SERVICE_TOKEN milvus_uri
  export EMBEDDING_STRATEGY OPENAI_API_KEY COHERE_API_KEY GITHUB_WEBHOOK_SECRET
  export temporal_address TEMPORAL_TASK_QUEUE CHUNKER_STRATEGY LLM_STRATEGY

  python3 - <<'PY'
import json
import os
from pathlib import Path

def write(path_env: str, payload: dict) -> None:
    Path(os.environ[path_env]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

mcp_payload = {
    "DEBUG": os.environ["MCP_DEBUG"].lower() == "true",
    "CORS_ALLOW_ORIGINS": [os.environ["web_url"]],
    "POSTGRES_DSN": os.environ["postgres_dsn"],
    "GITHUB_OAUTH_CLIENT_ID": os.environ["GITHUB_OAUTH_CLIENT_ID"],
    "GITHUB_OAUTH_CLIENT_SECRET": os.environ["GITHUB_OAUTH_CLIENT_SECRET"],
    "GITHUB_OAUTH_CALLBACK_URL": os.environ["github_callback_url"],
    "SESSION_ENCRYPTION_KEY": os.environ["SESSION_ENCRYPTION_KEY"],
    "WEB_CLIENT_URL": os.environ["web_url"],
    "SESSION_TTL_HOURS": int(os.environ["SESSION_TTL_HOURS"]),
    "AWS_REGION": os.environ["REGION"],
    "SEARCH_SERVICE_URL": os.environ["search_service_url"],
    "INGESTION_SERVICE_URL": os.environ["ingestion_service_url"],
    "INTERNAL_SERVICE_TOKEN": os.environ["INTERNAL_SERVICE_TOKEN"],
}

search_payload = {
    "POSTGRES_DSN": os.environ["postgres_dsn"],
    "MILVUS_URI": os.environ["milvus_uri"],
    "EMBEDDING_STRATEGY": os.environ["EMBEDDING_STRATEGY"],
    "OPENAI_API_KEY": os.environ["OPENAI_API_KEY"],
    "COHERE_API_KEY": os.environ["COHERE_API_KEY"],
    "INTERNAL_SERVICE_TOKEN": os.environ["INTERNAL_SERVICE_TOKEN"],
    "RERANK_MODEL": "rerank-v4.0-pro",
    "LLM_MODEL": "gpt-5.4-nano",
    "LLM_REASONING_EFFORT": "none",
}

ingestion_payload = {
    "POSTGRES_DSN": os.environ["postgres_dsn"],
    "MILVUS_URI": os.environ["milvus_uri"],
    "OPENAI_API_KEY": os.environ["OPENAI_API_KEY"],
    "GITHUB_WEBHOOK_SECRET": os.environ["GITHUB_WEBHOOK_SECRET"],
    "INTERNAL_SERVICE_TOKEN": os.environ["INTERNAL_SERVICE_TOKEN"],
    "CLONE_BASE_DIR": "/tmp/lighthouse_repos",
    "TEMPORAL_ADDRESS": os.environ["temporal_address"],
    "TEMPORAL_TASK_QUEUE": os.environ["TEMPORAL_TASK_QUEUE"],
    "CHUNKER_STRATEGY": os.environ["CHUNKER_STRATEGY"],
    "EMBEDDING_STRATEGY": os.environ["EMBEDDING_STRATEGY"],
    "EMBEDDING_MODEL": "",
    "EMBEDDING_DIMENSION": 0,
    "LLM_STRATEGY": os.environ["LLM_STRATEGY"],
    "LLM_MODEL": "",
    "LLM_REASONING_EFFORT": "",
}

write("MCP_SSM_JSON", mcp_payload)
write("SEARCH_SSM_JSON", search_payload)
write("INGESTION_SSM_JSON", ingestion_payload)
PY
}

run_db_migration() {
  local cluster_name="$1"
  local task_definition_arn="$2"
  local subnets_json="$3"
  local security_group_id="$4"

  local subnets_csv
  subnets_csv="$(python3 - <<'PY' "$subnets_json"
import json
import sys
print(",".join(json.loads(sys.argv[1])))
PY
)"

  local task_arn
  task_arn="$(
    aws ecs run-task \
      --cluster "$cluster_name" \
      --launch-type FARGATE \
      --task-definition "$task_definition_arn" \
      --network-configuration "awsvpcConfiguration={subnets=[${subnets_csv}],securityGroups=[${security_group_id}],assignPublicIp=DISABLED}" \
      --region "$REGION" \
      --query 'tasks[0].taskArn' \
      --output text
  )"

  if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
    echo "Failed to start DB migration task" >&2
    exit 1
  fi

  aws ecs wait tasks-stopped --cluster "$cluster_name" --tasks "$task_arn" --region "$REGION"

  local exit_code
  exit_code="$(
    aws ecs describe-tasks \
      --cluster "$cluster_name" \
      --tasks "$task_arn" \
      --region "$REGION" \
      --query 'tasks[0].containers[0].exitCode' \
      --output text
  )"

  if [[ "$exit_code" != "0" ]]; then
    echo "DB migration task failed with exit code ${exit_code}" >&2
    exit 1
  fi
}

force_service_deployments() {
  local cluster_name="$1"
  local services=(
    "${PROJECT_NAME}-${ENVIRONMENT}-mcp"
    "${PROJECT_NAME}-${ENVIRONMENT}-search"
    "${PROJECT_NAME}-${ENVIRONMENT}-ingestion"
    "${PROJECT_NAME}-${ENVIRONMENT}-ingestion-worker"
    "${PROJECT_NAME}-${ENVIRONMENT}-web"
  )

  for service in "${services[@]}"; do
    aws ecs update-service \
      --cluster "$cluster_name" \
      --service "$service" \
      --force-new-deployment \
      --region "$REGION" >/dev/null
  done

  aws ecs wait services-stable \
    --cluster "$cluster_name" \
    --services "${services[@]}" \
    --region "$REGION"
}

echo "Building and pushing Docker images"
REGION="$REGION" \
ACCOUNT_ID="$ACCOUNT_ID" \
TAG="$TAG" \
WEB_REPO="$WEB_REPO" \
MCP_REPO="$MCP_REPO" \
SEARCH_REPO="$SEARCH_REPO" \
INGEST_REPO="$INGEST_REPO" \
  "${REPO_ROOT}/scripts/build_and_push_images.sh"

if [[ "${CLEAN_TERRAFORM_DIR:-1}" == "1" ]]; then
  rm -rf "${INFRA_DIR}/.terraform"
fi

echo "Initializing Terraform"
terraform -chdir="$INFRA_DIR" init -upgrade -reconfigure

echo "Applying base infrastructure"
terraform_apply \
  -target=module.networking \
  -target=module.database \
  -target=module.compute.aws_ecs_cluster.main \
  -target=module.compute.aws_cloudwatch_log_group.db_migrate \
  -target=module.compute.aws_iam_role.ecs_execution_role \
  -target=module.compute.aws_iam_role_policy_attachment.ecs_exec_attach \
  -target=module.compute.aws_iam_role.ecs_task_role \
  -target=module.compute.aws_iam_policy.ecs_task_policy \
  -target=module.compute.aws_iam_role_policy_attachment.ecs_task_attach \
  -target=module.compute.aws_security_group.alb \
  -target=module.compute.aws_security_group.app_tasks \
  -target=module.compute.aws_security_group.stateful_ec2 \
  -target=module.compute.aws_lb.public \
  -target=module.compute.aws_instance.temporal \
  -target=module.compute.aws_instance.milvus \
  -target=module.compute.aws_ecs_task_definition.db_migrate

DB_ENDPOINT="$(terraform -chdir="$INFRA_DIR" output -raw db_endpoint)"
WEB_URL="$(terraform -chdir="$INFRA_DIR" output -raw web_url)"
MCP_BASE_URL="$(terraform -chdir="$INFRA_DIR" output -raw mcp_base_url)"
TEMPORAL_PRIVATE_IP="$(terraform -chdir="$INFRA_DIR" output -raw temporal_private_ip)"
MILVUS_PRIVATE_IP="$(terraform -chdir="$INFRA_DIR" output -raw milvus_private_ip)"
CLUSTER_NAME="$(terraform -chdir="$INFRA_DIR" output -raw cluster_name)"
APP_TASKS_SG_ID="$(terraform -chdir="$INFRA_DIR" output -raw app_tasks_sg_id)"
DB_MIGRATE_TASK_DEFINITION_ARN="$(terraform -chdir="$INFRA_DIR" output -raw db_migrate_task_definition_arn)"
PRIVATE_SUBNET_IDS_JSON="$(terraform -chdir="$INFRA_DIR" output -json private_subnet_ids)"

echo "Writing SSM parameter payloads"
write_ssm_payloads "$DB_ENDPOINT" "$WEB_URL" "$MCP_BASE_URL" "$TEMPORAL_PRIVATE_IP" "$MILVUS_PRIVATE_IP"
put_ssm_parameter "$MCP_SSM_NAME" "$MCP_SSM_JSON"
put_ssm_parameter "$SEARCH_SSM_NAME" "$SEARCH_SSM_JSON"
put_ssm_parameter "$INGESTION_SSM_NAME" "$INGESTION_SSM_JSON"

echo "Running database migrations"
run_db_migration "$CLUSTER_NAME" "$DB_MIGRATE_TASK_DEFINITION_ARN" "$PRIVATE_SUBNET_IDS_JSON" "$APP_TASKS_SG_ID"

echo "Applying full infrastructure"
terraform_apply

echo "Forcing ECS services to pick up the latest SSM settings"
force_service_deployments "$CLUSTER_NAME"

cat <<EOF

Deployment complete.

Web URL: ${WEB_URL}
MCP base URL: ${MCP_BASE_URL}
Webhook URL: $(terraform -chdir="$INFRA_DIR" output -raw ingestion_webhook_url)

SSM parameters:
  ${MCP_SSM_NAME}
  ${SEARCH_SSM_NAME}
  ${INGESTION_SSM_NAME}

You can smoke test with:
  curl ${WEB_URL}
  curl ${MCP_BASE_URL}/health
EOF
