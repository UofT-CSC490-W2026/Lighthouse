#!/usr/bin/env bash
set -euo pipefail

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REGION="${REGION:-us-east-1}"
TAG="${TAG:-latest}"
ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"

WEB_REPO="${WEB_REPO:-lighthouse-prod-web}"
MCP_REPO="${MCP_REPO:-lighthouse-prod-mcp}"
SEARCH_REPO="${SEARCH_REPO:-lighthouse-prod-search}"
INGEST_REPO="${INGEST_REPO:-lighthouse-prod-ingestion}"

WEB_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${WEB_REPO}:${TAG}"
MCP_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${MCP_REPO}:${TAG}"
SEARCH_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${SEARCH_REPO}:${TAG}"
INGEST_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${INGEST_REPO}:${TAG}"

ensure_repo() {
  local repo="$1"
  aws ecr describe-repositories --repository-names "$repo" --region "$REGION" >/dev/null 2>&1 || \
    aws ecr create-repository --repository-name "$repo" --region "$REGION" >/dev/null
}

echo "Using AWS account ${ACCOUNT_ID} in ${REGION}"
echo "Using image tag ${TAG}"

ensure_repo "$WEB_REPO"
ensure_repo "$MCP_REPO"
ensure_repo "$SEARCH_REPO"
ensure_repo "$INGEST_REPO"

aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

cd "$REPO_ROOT"

docker build -f services/web/Dockerfile -t "$WEB_URI" .
docker build -f services/mcp_server/Dockerfile -t "$MCP_URI" .
docker build -f services/search/Dockerfile -t "$SEARCH_URI" .
docker build -f services/ingestion/Dockerfile -t "$INGEST_URI" .

docker push "$WEB_URI"
docker push "$MCP_URI"
docker push "$SEARCH_URI"
docker push "$INGEST_URI"

cat <<EOF

Built and pushed image URIs:
  web_image       = "$WEB_URI"
  mcp_image       = "$MCP_URI"
  search_image    = "$SEARCH_URI"
  ingestion_image = "$INGEST_URI"

Update:
  ./infra/terraform.tfvars
EOF
