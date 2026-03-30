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
Reset Lighthouse auth state after a SESSION_ENCRYPTION_KEY mismatch.

This clears only the Fernet-backed auth/session fields:
- users.api_token_hash / api_token_encrypted / api_token_issued_at
- users.mcp_token_hash / mcp_token_encrypted / mcp_token_issued_at
- all rows in sessions

It does not drop the schema or remove repositories, chunks, or other indexing data.

Usage:
  scripts/reset_auth_state.sh [--dsn <postgres-dsn>] [--dry-run] [--yes]

Options:
  --dsn <dsn>  PostgreSQL DSN to connect with. Defaults to POSTGRES_DSN, then DATABASE_URL.
               Accepts either postgresql://... or postgresql+asyncpg://...
  --dry-run    Show the affected row counts without making changes.
  --yes        Skip the interactive confirmation prompt.
  -h, --help   Show this help text.
EOF
}

require_cmd psql

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DRY_RUN=0
ASSUME_YES=0
DSN="${POSTGRES_DSN:-${DATABASE_URL:-}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dsn)
      DSN="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
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

if [[ -z "$DSN" ]]; then
  echo "A PostgreSQL DSN is required. Set POSTGRES_DSN or pass --dsn." >&2
  exit 1
fi

NORMALIZED_DSN="${DSN/postgresql+asyncpg:\/\//postgresql://}"
REDACTED_DSN="$(printf '%s' "$NORMALIZED_DSN" | sed -E 's#(postgresql://[^:]+:)[^@]+@#\1****@#')"

READ_SQL=$(cat <<'EOF'
SELECT
  COUNT(*) FILTER (
    WHERE api_token_hash IS NOT NULL
       OR api_token_encrypted IS NOT NULL
       OR api_token_issued_at IS NOT NULL
       OR mcp_token_hash IS NOT NULL
       OR mcp_token_encrypted IS NOT NULL
       OR mcp_token_issued_at IS NOT NULL
  ) AS affected_users,
  (SELECT COUNT(*) FROM sessions) AS sessions_to_delete
FROM users;
EOF
)

RESET_SQL=$(cat <<'EOF'
BEGIN;

UPDATE users
SET
  api_token_hash = NULL,
  api_token_encrypted = NULL,
  api_token_issued_at = NULL,
  mcp_token_hash = NULL,
  mcp_token_encrypted = NULL,
  mcp_token_issued_at = NULL
WHERE
  api_token_hash IS NOT NULL
  OR api_token_encrypted IS NOT NULL
  OR api_token_issued_at IS NOT NULL
  OR mcp_token_hash IS NOT NULL
  OR mcp_token_encrypted IS NOT NULL
  OR mcp_token_issued_at IS NOT NULL;

DELETE FROM sessions;

COMMIT;
EOF
)

echo "Target database: $REDACTED_DSN"
echo
echo "Current auth-state impact:"
psql "$NORMALIZED_DSN" -X -v ON_ERROR_STOP=1 -P pager=off -c "$READ_SQL"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "Dry run only. No changes were applied."
  exit 0
fi

if [[ "$ASSUME_YES" -ne 1 ]]; then
  echo
  read -r -p "Proceed with auth-state reset? Type 'reset-auth-state' to continue: " confirmation
  if [[ "$confirmation" != "reset-auth-state" ]]; then
    echo "Cancelled."
    exit 1
  fi
fi

echo
psql "$NORMALIZED_DSN" -X -v ON_ERROR_STOP=1 -c "$RESET_SQL"

echo
echo "Auth-state reset complete."
echo "Next steps:"
echo "- Redeploy MCP with the stable SESSION_ENCRYPTION_KEY for this environment."
echo "- Sign in again through GitHub OAuth."
echo "- Reissue any MCP token from the UI if needed."
