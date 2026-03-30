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

    case "$service_dir" in
        */mcp_server)
            (
                ENV_PATH="$env_path"
                export ENV_PATH
                cd "$repo_root/services/mcp_server"
                uv run python -c \
'import os, re
from pathlib import Path
from cryptography.fernet import Fernet
p = Path(os.environ["ENV_PATH"])
text = p.read_text()
key = Fernet.generate_key().decode()
p.write_text(re.sub(r"^SESSION_ENCRYPTION_KEY=.*$", "SESSION_ENCRYPTION_KEY=" + key, text, flags=re.M))'
            )
            printf 'Generated SESSION_ENCRYPTION_KEY in %s\n' "$env_path"
            ;;
        */ingestion)
            (
                ENV_PATH="$env_path"
                export ENV_PATH
                cd "$repo_root"
                uv run python -c \
'import os, re, secrets
from pathlib import Path
p = Path(os.environ["ENV_PATH"])
text = p.read_text()
secret = secrets.token_hex(32)
p.write_text(re.sub(r"^GITHUB_WEBHOOK_SECRET=.*$", "GITHUB_WEBHOOK_SECRET=" + secret, text, flags=re.M))'
            )
            printf 'Generated GITHUB_WEBHOOK_SECRET in %s\n' "$env_path"
            ;;
    esac
done
