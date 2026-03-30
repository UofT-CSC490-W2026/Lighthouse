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
