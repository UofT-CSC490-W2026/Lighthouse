#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required" >&2
    exit 1
  fi
}

usage() {
  cat <<'EOF'
Run the Lighthouse auth-state reset inside AWS as a one-off ECS task.

This is useful when RDS is private and not reachable from your laptop. The script
reuses the existing db-migrate task definition so the work runs in the same VPC,
private subnets, and app task security group that already have database access.

Usage:
  scripts/reset_auth_state_aws.sh [--dry-run] [--yes]

Options:
  --dry-run    Show the affected row counts without applying the reset.
  --yes        Skip the interactive confirmation prompt.
  -h, --help   Show this help text.

Environment:
  ENV_FILE     Override the env file to load. Defaults to .env.deploy if present.
  TFVARS_PATH  Override the Terraform tfvars path. Defaults to infra/terraform.tfvars.
  POSTGRES_DSN Use this exact DSN instead of constructing one from Terraform outputs
               and DB_* variables.
EOF
}

require_cmd aws
require_cmd terraform
require_cmd python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${REPO_ROOT}/infra"
BASE_TFVARS="${TFVARS_PATH:-${INFRA_DIR}/terraform.tfvars}"
HELPER="${SCRIPT_DIR}/deploy_aws_stack_helper.py"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env.deploy}"

if [[ ! -f "$BASE_TFVARS" ]]; then
  echo "Terraform var file not found: $BASE_TFVARS" >&2
  exit 1
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

read_tfvar_string() {
  local key="$1"
  python3 "$HELPER" read-tfvar --path "$BASE_TFVARS" --key "$key"
}

REGION="${REGION:-$(read_tfvar_string aws_region)}"
DB_NAME="${DB_NAME:-$(read_tfvar_string db_name)}"
DB_USERNAME="${DB_USERNAME:-$(read_tfvar_string db_username)}"
DB_PASSWORD="${DB_PASSWORD:-}"
POSTGRES_DSN="${POSTGRES_DSN:-}"

MODE="execute"
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLUSTER_NAME="$(terraform -chdir="$INFRA_DIR" output -raw cluster_name)"
TASK_DEFINITION_ARN="$(terraform -chdir="$INFRA_DIR" output -raw db_migrate_task_definition_arn)"
APP_TASKS_SG_ID="$(terraform -chdir="$INFRA_DIR" output -raw app_tasks_sg_id)"
DB_ENDPOINT="$(terraform -chdir="$INFRA_DIR" output -raw db_endpoint)"
PRIVATE_SUBNETS_JSON="$(terraform -chdir="$INFRA_DIR" output -json private_subnet_ids)"
PRIVATE_SUBNETS_CSV="$(python3 "$HELPER" json-array-csv --json "$PRIVATE_SUBNETS_JSON")"

if [[ -z "$POSTGRES_DSN" ]]; then
  if [[ -z "$DB_PASSWORD" ]]; then
    echo "DB_PASSWORD must be set in $ENV_FILE or POSTGRES_DSN must be provided explicitly." >&2
    exit 1
  fi
  POSTGRES_DSN="postgresql://${DB_USERNAME}:${DB_PASSWORD}@${DB_ENDPOINT}/${DB_NAME}"
fi

NORMALIZED_DSN="${POSTGRES_DSN/postgresql+asyncpg:\/\//postgresql://}"
REDACTED_DSN="$(printf '%s' "$NORMALIZED_DSN" | sed -E 's#(postgresql://[^:]+:)[^@]+@#\\1****@#')"

if [[ "$ASSUME_YES" -ne 1 && "$MODE" == "execute" ]]; then
  echo "Target database: $REDACTED_DSN"
  echo "Cluster: $CLUSTER_NAME"
  echo
  read -r -p "Run the auth-state reset task in AWS? Type 'reset-auth-state' to continue: " confirmation
  if [[ "$confirmation" != "reset-auth-state" ]]; then
    echo "Cancelled."
    exit 1
  fi
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
OVERRIDES_PATH="${TMP_DIR}/overrides.json"

python3 "$HELPER" write-reset-auth-state-overrides \
  --out "$OVERRIDES_PATH" \
  --container-name "db-migrate" \
  --postgres-dsn "$NORMALIZED_DSN" \
  --mode "$MODE"

TASK_ARN="$(aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type FARGATE \
  --task-definition "$TASK_DEFINITION_ARN" \
  --network-configuration "awsvpcConfiguration={subnets=[${PRIVATE_SUBNETS_CSV}],securityGroups=[${APP_TASKS_SG_ID}],assignPublicIp=DISABLED}" \
  --overrides "file://${OVERRIDES_PATH}" \
  --region "$REGION" \
  --query 'tasks[0].taskArn' \
  --output text)"

if [[ -z "$TASK_ARN" || "$TASK_ARN" == "None" ]]; then
  echo "Failed to start ECS task." >&2
  exit 1
fi

TASK_ID="${TASK_ARN##*/}"
LOG_GROUP="/ecs/$(read_tfvar_string project_name)/$(read_tfvar_string environment)/db-migrate"
LOG_STREAM="ecs/db-migrate/${TASK_ID}"

echo "Started task: $TASK_ARN"
echo "Waiting for task to stop..."
aws ecs wait tasks-stopped --cluster "$CLUSTER_NAME" --tasks "$TASK_ARN" --region "$REGION"

EXIT_CODE="$(aws ecs describe-tasks \
  --cluster "$CLUSTER_NAME" \
  --tasks "$TASK_ARN" \
  --region "$REGION" \
  --query 'tasks[0].containers[0].exitCode' \
  --output text)"

STOPPED_REASON="$(aws ecs describe-tasks \
  --cluster "$CLUSTER_NAME" \
  --tasks "$TASK_ARN" \
  --region "$REGION" \
  --query 'tasks[0].stoppedReason' \
  --output text)"

CONTAINER_REASON="$(aws ecs describe-tasks \
  --cluster "$CLUSTER_NAME" \
  --tasks "$TASK_ARN" \
  --region "$REGION" \
  --query 'tasks[0].containers[0].reason' \
  --output text)"

echo
echo "Task stopped reason: $STOPPED_REASON"
echo "Container reason: $CONTAINER_REASON"
echo "Exit code: $EXIT_CODE"
echo

aws logs get-log-events \
  --log-group-name "$LOG_GROUP" \
  --log-stream-name "$LOG_STREAM" \
  --region "$REGION" \
  --query 'events[*].message' \
  --output text || true

if [[ "$EXIT_CODE" != "0" ]]; then
  exit 1
fi

if [[ "$MODE" == "dry-run" ]]; then
  echo
  echo "Dry run complete. No changes were applied."
else
  echo
  echo "Auth-state reset complete."
  echo "Next steps:"
  echo "- Redeploy MCP with the stable SESSION_ENCRYPTION_KEY for this environment."
  echo "- Sign in again through GitHub OAuth."
  echo "- Reissue any MCP token from the UI if needed."
fi
