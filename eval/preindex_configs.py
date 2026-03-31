from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval.synthetic.lighthouse import index_synthetic_repository, prepare_synthetic_wiki
from eval.synthetic.workspace import prepare_synthetic_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_GLOB = "eval/configs/generated/*.json"
DEFAULT_WORKSPACE_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_workspace" / "queued"


def _read_config(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Config must be an object: {path}")
    return raw


def _singleton_value(config: dict[str, Any], field_name: str) -> Any:
    values = config.get(field_name)
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError(f"{field_name} must be a singleton list in this workflow")
    return values[0]


def _preindex_keys(config_paths: list[Path]) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    index_keys: set[tuple[Any, ...]] = set()
    wiki_keys: set[tuple[Any, ...]] = set()
    for path in config_paths:
        cfg = _read_config(path)
        family = str(_singleton_value(cfg, "families"))
        chunking = str(_singleton_value(cfg, "chunking_strategies"))
        embedding_model = str(_singleton_value(cfg, "embedding_models"))
        embedding_strategy = str(cfg.get("embedding_strategy", "")).strip()
        task_count = int(cfg.get("task_count", 30))
        seed = cfg.get("seed")
        shared_library_repo_count = cfg.get("shared_library_repo_count")
        index_keys.add(
            (
                family,
                chunking,
                embedding_strategy,
                embedding_model,
                task_count,
                seed,
                shared_library_repo_count,
            )
        )
        wiki_keys.add((family, task_count, seed, shared_library_repo_count))
    return sorted(index_keys), sorted(wiki_keys)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-index synthetic repositories exactly once per "
            "(family, chunking, embedding_strategy, embedding_model)."
        )
    )
    parser.add_argument(
        "--config-glob",
        default=DEFAULT_CONFIG_GLOB,
        help="Glob pattern for singleton matrix configs",
    )
    parser.add_argument(
        "--workspace-root",
        default=str(DEFAULT_WORKSPACE_ROOT),
        help="Workspace root shared with queued runs",
    )
    parser.add_argument("--ingestion-url", default="http://localhost:8001")
    parser.add_argument("--github-token", default=None)
    parser.add_argument("--status-poll-interval", type=float, default=2.0)
    parser.add_argument("--progress-heartbeat-seconds", type=float, default=10.0)
    parser.add_argument("--status-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--wiki-poll-interval", type=float, default=2.0)
    parser.add_argument("--wiki-progress-heartbeat-seconds", type=float, default=10.0)
    parser.add_argument("--wiki-timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--stream-worker-logs",
        action="store_true",
        help="Stream local ingestion-worker logs while indexing",
    )
    parser.add_argument(
        "--skip-wiki",
        action="store_true",
        help="Skip one-time synthetic wiki preparation per family.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_paths = sorted(REPO_ROOT.glob(args.config_glob))
    if not config_paths:
        raise RuntimeError(f"No configs matched: {args.config_glob}")

    index_keys, wiki_keys = _preindex_keys(config_paths)
    workspace_root = Path(args.workspace_root).resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(config_paths)} configs")
    print(f"Unique index groups: {len(index_keys)}")
    print(f"Unique wiki groups: {len(wiki_keys)}")

    for key in index_keys:
        (
            family,
            chunking,
            embedding_strategy,
            embedding_model,
            task_count,
            seed,
            shared_library_repo_count,
        ) = key
        include_ast = chunking == "ast"
        workspace = prepare_synthetic_workspace(
            family_name=family,
            task_count=task_count,
            seed=seed,
            shared_library_repo_count=shared_library_repo_count,
            workspace_root=workspace_root,
            force=False,
        )
        print(
            "Pre-indexing "
            f"family={family} chunking={chunking} "
            f"embedding_strategy={embedding_strategy} embedding_model={embedding_model}"
        )
        index_synthetic_repository(
            workspace=workspace,
            ingestion_url=args.ingestion_url,
            github_token=args.github_token,
            stream_worker_logs=args.stream_worker_logs,
            poll_interval_seconds=args.status_poll_interval,
            progress_heartbeat_seconds=args.progress_heartbeat_seconds,
            timeout_seconds=args.status_timeout_seconds,
            include_ast=include_ast,
            embedding_strategy=embedding_strategy,
            embedding_model=embedding_model,
        )

    if not args.skip_wiki:
        for family, task_count, seed, shared_library_repo_count in wiki_keys:
            workspace = prepare_synthetic_workspace(
                family_name=family,
                task_count=task_count,
                seed=seed,
                shared_library_repo_count=shared_library_repo_count,
                workspace_root=workspace_root,
                force=False,
            )
            print(f"Preparing wiki family={family}")
            prepare_synthetic_wiki(
                workspace=workspace,
                ingestion_url=args.ingestion_url,
                poll_interval_seconds=args.wiki_poll_interval,
                progress_heartbeat_seconds=args.wiki_progress_heartbeat_seconds,
                timeout_seconds=args.wiki_timeout_seconds,
            )

    print("Pre-indexing completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
