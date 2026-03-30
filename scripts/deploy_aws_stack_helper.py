#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import secrets
import sys
import textwrap


RESET_AUTH_STATE_INLINE_PYTHON = textwrap.dedent(
    """
    import asyncio
    import os

    import asyncpg


    READ_SQL = '''
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
    '''

    RESET_SQL = '''
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
    '''


    async def main() -> None:
        dsn = os.environ["POSTGRES_DSN"]
        mode = os.environ.get("RESET_AUTH_STATE_MODE", "execute").strip().lower()
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(READ_SQL)
            affected_users = int(row["affected_users"])
            sessions_to_delete = int(row["sessions_to_delete"])
            print(f"affected_users={affected_users}")
            print(f"sessions_to_delete={sessions_to_delete}")

            if mode == "dry-run":
                print("dry_run=true")
                return

            async with conn.transaction():
                await conn.execute(RESET_SQL)

            print("reset_applied=true")
        finally:
            await conn.close()


    asyncio.run(main())
    """
).strip()


def read_tfvar_string(path: str, key: str) -> None:
    text = pathlib.Path(path).read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}\s*=\s*\"([^\"]*)\"", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"Could not find string tfvar {key!r} in {path}")
    print(match.group(1))


def generate_fernet_key() -> None:
    print(base64.urlsafe_b64encode(os.urandom(32)).decode())


def generate_token(num_bytes: int) -> None:
    print(secrets.token_hex(num_bytes))


def write_generated_tfvars(args: argparse.Namespace) -> None:
    payload = {
        "web_image": args.web_image,
        "mcp_image": args.mcp_image,
        "search_image": args.search_image,
        "ingestion_image": args.ingestion_image,
        "mcp_server_settings_ssm_parameter_name": args.mcp_ssm_name,
        "mcp_server_settings_ssm_parameter_arn": args.mcp_ssm_arn,
        "search_settings_ssm_parameter_name": args.search_ssm_name,
        "search_settings_ssm_parameter_arn": args.search_ssm_arn,
        "ingestion_settings_ssm_parameter_name": args.ingestion_ssm_name,
        "ingestion_settings_ssm_parameter_arn": args.ingestion_ssm_arn,
        "db_password": args.db_password,
    }
    pathlib.Path(args.out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_json(path: str, payload: dict) -> None:
    pathlib.Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def maybe_set(payload: dict[str, object], key: str, value: str) -> None:
    if value.strip():
        payload[key] = value


def write_ssm_payloads(args: argparse.Namespace) -> None:
    mcp_payload = {
        "DEBUG": args.mcp_debug,
        "CORS_ALLOW_ORIGINS": [args.web_url],
        "POSTGRES_DSN": args.postgres_dsn,
        "GITHUB_OAUTH_CLIENT_ID": args.github_oauth_client_id,
        "GITHUB_OAUTH_CLIENT_SECRET": args.github_oauth_client_secret,
        "GITHUB_OAUTH_CALLBACK_URL": args.github_callback_url,
        "SESSION_ENCRYPTION_KEY": args.session_encryption_key,
        "WEB_CLIENT_URL": args.web_url,
        "SESSION_TTL_HOURS": args.session_ttl_hours,
        "AWS_REGION": args.region,
        "SEARCH_SERVICE_URL": args.search_service_url,
        "INGESTION_SERVICE_URL": args.ingestion_service_url,
        "INTERNAL_SERVICE_TOKEN": args.internal_service_token,
    }

    search_payload = {
        "POSTGRES_DSN": args.postgres_dsn,
        "MILVUS_URI": args.milvus_uri,
        "EMBEDDING_STRATEGY": args.search_embedding_strategy,
        "OPENAI_API_KEY": args.openai_api_key,
        "COHERE_API_KEY": args.cohere_api_key,
        "INTERNAL_SERVICE_TOKEN": args.internal_service_token,
        "RERANK_MODEL": args.search_rerank_model,
        "LLM_MODEL": args.search_llm_model,
        "LLM_REASONING_EFFORT": args.search_llm_reasoning_effort,
    }
    maybe_set(search_payload, "EMBEDDING_MODEL", args.search_embedding_model)

    ingestion_payload = {
        "POSTGRES_DSN": args.postgres_dsn,
        "MILVUS_URI": args.milvus_uri,
        "OPENAI_API_KEY": args.openai_api_key,
        "GITHUB_WEBHOOK_SECRET": args.github_webhook_secret,
        "INTERNAL_SERVICE_TOKEN": args.internal_service_token,
        "CLONE_BASE_DIR": args.ingestion_clone_base_dir,
        "TEMPORAL_ADDRESS": args.temporal_address,
        "TEMPORAL_NAMESPACE": args.temporal_namespace,
        "TEMPORAL_API_KEY": args.temporal_api_key,
        "TEMPORAL_TASK_QUEUE": args.temporal_task_queue,
        "CHUNKER_STRATEGY": args.chunker_strategy,
        "EMBEDDING_STRATEGY": args.ingestion_embedding_strategy,
        "LLM_STRATEGY": args.ingestion_llm_strategy,
    }
    maybe_set(ingestion_payload, "EMBEDDING_MODEL", args.ingestion_embedding_model)
    if args.ingestion_embedding_dimension > 0:
        ingestion_payload["EMBEDDING_DIMENSION"] = args.ingestion_embedding_dimension
    maybe_set(ingestion_payload, "LLM_MODEL", args.ingestion_llm_model)
    maybe_set(ingestion_payload, "LLM_REASONING_EFFORT", args.ingestion_llm_reasoning_effort)

    write_json(args.mcp_out, mcp_payload)
    write_json(args.search_out, search_payload)
    write_json(args.ingestion_out, ingestion_payload)


def json_array_csv(raw_json: str) -> None:
    values = json.loads(raw_json)
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise SystemExit("Expected a JSON array of strings")
    print(",".join(values))


def write_reset_auth_state_overrides(args: argparse.Namespace) -> None:
    payload = {
        "containerOverrides": [
            {
                "name": args.container_name,
                "command": ["python", "-c", RESET_AUTH_STATE_INLINE_PYTHON],
                "environment": [
                    {"name": "POSTGRES_DSN", "value": args.postgres_dsn},
                    {"name": "RESET_AUTH_STATE_MODE", "value": args.mode},
                ],
            }
        ]
    }
    pathlib.Path(args.out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Helpers for AWS stack deployment scripts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_tfvar = subparsers.add_parser("read-tfvar")
    read_tfvar.add_argument("--path", required=True)
    read_tfvar.add_argument("--key", required=True)

    subparsers.add_parser("generate-fernet-key")

    gen_token = subparsers.add_parser("generate-token")
    gen_token.add_argument("--num-bytes", type=int, default=32)

    tfvars = subparsers.add_parser("write-generated-tfvars")
    tfvars.add_argument("--out", required=True)
    tfvars.add_argument("--web-image", required=True)
    tfvars.add_argument("--mcp-image", required=True)
    tfvars.add_argument("--search-image", required=True)
    tfvars.add_argument("--ingestion-image", required=True)
    tfvars.add_argument("--mcp-ssm-name", required=True)
    tfvars.add_argument("--mcp-ssm-arn", required=True)
    tfvars.add_argument("--search-ssm-name", required=True)
    tfvars.add_argument("--search-ssm-arn", required=True)
    tfvars.add_argument("--ingestion-ssm-name", required=True)
    tfvars.add_argument("--ingestion-ssm-arn", required=True)
    tfvars.add_argument("--db-password", required=True)

    ssm = subparsers.add_parser("write-ssm-payloads")
    ssm.add_argument("--mcp-out", required=True)
    ssm.add_argument("--search-out", required=True)
    ssm.add_argument("--ingestion-out", required=True)
    ssm.add_argument("--mcp-debug", action="store_true")
    ssm.add_argument("--web-url", required=True)
    ssm.add_argument("--postgres-dsn", required=True)
    ssm.add_argument("--github-oauth-client-id", required=True)
    ssm.add_argument("--github-oauth-client-secret", required=True)
    ssm.add_argument("--github-callback-url", required=True)
    ssm.add_argument("--session-encryption-key", required=True)
    ssm.add_argument("--session-ttl-hours", type=int, required=True)
    ssm.add_argument("--region", required=True)
    ssm.add_argument("--search-service-url", required=True)
    ssm.add_argument("--ingestion-service-url", required=True)
    ssm.add_argument("--internal-service-token", required=True)
    ssm.add_argument("--milvus-uri", required=True)
    ssm.add_argument("--search-embedding-strategy", required=True)
    ssm.add_argument("--search-embedding-model", default="")
    ssm.add_argument("--search-rerank-model", required=True)
    ssm.add_argument("--search-llm-model", required=True)
    ssm.add_argument("--search-llm-reasoning-effort", required=True)
    ssm.add_argument("--openai-api-key", default="")
    ssm.add_argument("--cohere-api-key", default="")
    ssm.add_argument("--github-webhook-secret", required=True)
    ssm.add_argument("--ingestion-clone-base-dir", required=True)
    ssm.add_argument("--temporal-address", required=True)
    ssm.add_argument("--temporal-namespace", required=True)
    ssm.add_argument("--temporal-api-key", required=True)
    ssm.add_argument("--temporal-task-queue", required=True)
    ssm.add_argument("--chunker-strategy", required=True)
    ssm.add_argument("--ingestion-embedding-strategy", required=True)
    ssm.add_argument("--ingestion-embedding-model", default="")
    ssm.add_argument("--ingestion-embedding-dimension", type=int, default=0)
    ssm.add_argument("--ingestion-llm-strategy", required=True)
    ssm.add_argument("--ingestion-llm-model", default="")
    ssm.add_argument("--ingestion-llm-reasoning-effort", default="")

    array_csv = subparsers.add_parser("json-array-csv")
    array_csv.add_argument("--json", required=True)

    reset_overrides = subparsers.add_parser("write-reset-auth-state-overrides")
    reset_overrides.add_argument("--out", required=True)
    reset_overrides.add_argument("--container-name", required=True)
    reset_overrides.add_argument("--postgres-dsn", required=True)
    reset_overrides.add_argument("--mode", choices=["dry-run", "execute"], required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "read-tfvar":
        read_tfvar_string(args.path, args.key)
    elif args.command == "generate-fernet-key":
        generate_fernet_key()
    elif args.command == "generate-token":
        generate_token(args.num_bytes)
    elif args.command == "write-generated-tfvars":
        write_generated_tfvars(args)
    elif args.command == "write-ssm-payloads":
        write_ssm_payloads(args)
    elif args.command == "json-array-csv":
        json_array_csv(args.json)
    elif args.command == "write-reset-auth-state-overrides":
        write_reset_auth_state_overrides(args)
    else:
        raise SystemExit(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
