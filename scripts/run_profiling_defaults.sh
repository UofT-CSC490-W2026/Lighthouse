#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

QUICK=0
DUMP_PROF=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)
      QUICK=1
      shift
      ;;
    --dump-prof)
      DUMP_PROF=1
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Run default cProfile workloads for Lighthouse profiling scripts.

Usage:
  scripts/run_profiling_defaults.sh [--quick] [--dump-prof]

Options:
  --quick      Run smaller/faster workloads for smoke checks.
  --dump-prof  Persist .prof outputs in each service's profiles/artifacts directory.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

DUMP_ARG=()
if [[ "$DUMP_PROF" -eq 1 ]]; then
  DUMP_ARG=(--dump-prof)
fi

run_step() {
  local name="$1"
  shift
  echo
  echo "==> $name"
  "$PYTHON_BIN" "$@"
}

if [[ "$QUICK" -eq 1 ]]; then
  run_step \
    "SlidingWindowChunker (quick)" \
    services/ingestion/profiles/profile_sliding_window_chunker.py \
    --line-count 5000 --max-lines 1000 --overlap-lines 40 --repeat 1 --top-n 20 \
    "${DUMP_ARG[@]}"

  run_step \
    "GitOperations.list_files (quick)" \
    services/ingestion/profiles/profile_git_ops.py \
    --directories 15 --files-per-directory 40 --repeat 1 --top-n 20 \
    "${DUMP_ARG[@]}"

  run_step \
    "ChunkService.move_to_final (quick)" \
    services/ingestion/profiles/profile_chunk_service.py \
    --target move_to_final --chunk-count 1200 --changed-files 80 --repeat 1 --top-n 20 \
    "${DUMP_ARG[@]}"

  run_step \
    "ChunkService.publish_incremental_batch (quick)" \
    services/ingestion/profiles/profile_chunk_service.py \
    --target publish_incremental --chunk-count 1200 --changed-files 80 --repeat 1 --top-n 20 \
    "${DUMP_ARG[@]}"

  run_step \
    "HybridSearchStrategy targets (quick)" \
    services/search/profiles/profile_hybrid_strategy.py \
    --target all --size small --repeat 1 --top-n 20 \
    "${DUMP_ARG[@]}"
else
  run_step \
    "SlidingWindowChunker" \
    services/ingestion/profiles/profile_sliding_window_chunker.py \
    --line-count 25000 --max-lines 200 --overlap-lines 40 --repeat 3 --top-n 40 \
    "${DUMP_ARG[@]}"

  run_step \
    "GitOperations.list_files" \
    services/ingestion/profiles/profile_git_ops.py \
    --directories 60 --files-per-directory 80 --repeat 2 --top-n 40 \
    "${DUMP_ARG[@]}"

  run_step \
    "ChunkService.move_to_final" \
    services/ingestion/profiles/profile_chunk_service.py \
    --target move_to_final --chunk-count 8000 --changed-files 200 --repeat 1 --top-n 40 \
    "${DUMP_ARG[@]}"

  run_step \
    "ChunkService.publish_incremental_batch" \
    services/ingestion/profiles/profile_chunk_service.py \
    --target publish_incremental --chunk-count 8000 --changed-files 200 --repeat 1 --top-n 40 \
    "${DUMP_ARG[@]}"

  run_step \
    "HybridSearchStrategy targets" \
    services/search/profiles/profile_hybrid_strategy.py \
    --target all --size medium --repeat 2 --top-n 40 \
    "${DUMP_ARG[@]}"
fi

echo
echo "Completed profiling defaults."
