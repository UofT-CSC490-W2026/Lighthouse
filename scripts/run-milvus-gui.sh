#!/usr/bin/env bash
# Run [Attu](https://github.com/zilliztech/attu) against local Milvus.
#
# Host ports used by docker-compose.yml in this repo (avoid mapping these):
#   3000 web, 5432 postgres, 7233/8233 temporal, 8000 mcp_server,
#   8001 ingestion, 8002 search, 9001 minio console, 9091/19530 milvus
#
# Default Attu UI: http://localhost:8088 (override with ATTU_HOST_PORT).
#
# Milvus must be reachable from inside the Attu container. When Milvus runs
# via compose and publishes 19530 on the host, use host.docker.internal
# (not localhost).

set -euo pipefail

ATTU_HOST_PORT="${ATTU_HOST_PORT:-8088}"
MILVUS_URL="${MILVUS_URL:-host.docker.internal:19530}"
ATTU_IMAGE="${ATTU_IMAGE:-zilliz/attu:v2.6}"
ATTU_CONTAINER_NAME="${ATTU_CONTAINER_NAME:-lighthouse-attu}"

stop_attu() {
  docker stop -t 2 "${ATTU_CONTAINER_NAME}" &>/dev/null || true
}
trap stop_attu EXIT INT TERM

# Clear a leftover container (e.g. after Docker CLI bailed without stopping it).
docker rm -f "${ATTU_CONTAINER_NAME}" &>/dev/null || true

printf '\nOpen Attu in your browser:\n  http://127.0.0.1:%s\n  http://localhost:%s\n\n(Logs may show an http://172.x.x.x:3000 URL—that is inside the container;\nuse the localhost URL above from your machine.)\n\nStop: Ctrl+C, or in another terminal: docker stop %s\n\n' \
  "${ATTU_HOST_PORT}" "${ATTU_HOST_PORT}" "${ATTU_CONTAINER_NAME}"

docker run --rm --init \
  --name "${ATTU_CONTAINER_NAME}" \
  --add-host=host.docker.internal:host-gateway \
  -p "${ATTU_HOST_PORT}:3000" \
  -e "MILVUS_URL=${MILVUS_URL}" \
  "${ATTU_IMAGE}"
