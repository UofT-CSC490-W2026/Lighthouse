#!/usr/bin/env sh
set -eu

export POSTGRES_DSN="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@/${POSTGRES_DB}?host=/var/run/postgresql"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL

cd /opt/lighthouse/db
alembic upgrade head
