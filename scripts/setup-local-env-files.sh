#!/usr/bin/env sh
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

find "$repo_root/services" -name ".env.example" -type f | sort | while IFS= read -r example_path; do
    service_dir="$(dirname "$example_path")"
    env_path="$service_dir/.env"

    if [ -e "$env_path" ]; then
        printf 'Skipping %s; .env already exists\n' "$service_dir"
        continue
    fi

    cp "$example_path" "$env_path"
    printf 'Created %s\n' "$env_path"

done

cat <<'EOF'

Local .env files were copied only. Persistent secrets are no longer auto-generated.
Fill these in explicitly before running the stack:
- services/mcp_server/.env: SESSION_ENCRYPTION_KEY
- services/ingestion/.env: GITHUB_WEBHOOK_SECRET

You can generate values once and keep them stable, for example:
- SESSION_ENCRYPTION_KEY: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
- GITHUB_WEBHOOK_SECRET: python -c "import secrets; print(secrets.token_hex(32))"
EOF
