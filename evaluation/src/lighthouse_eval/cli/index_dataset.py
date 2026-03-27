from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import httpx
import yaml


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_config(path: Path):
    from lighthouse_eval.config import DatasetConfig, EvalConfig

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "dataset" in raw and isinstance(raw["dataset"], dict):
        raw["dataset"] = DatasetConfig(**raw["dataset"])
    return EvalConfig(**raw)


def _resolve_config_path(path: Path | None, *, config_path: Path) -> Path | None:
    if path is None or path.is_absolute():
        return path
    return (config_path.parent / path).resolve()


def _normalize_paths(config, config_path: Path) -> None:
    if config.dataset.path is not None:
        config.dataset.path = _resolve_config_path(
            config.dataset.path,
            config_path=config_path,
        )


def _adapter_config(config) -> dict:
    adapter_config = config.dataset.model_dump()
    adapter_config.update(adapter_config.pop("options", {}))
    return adapter_config


def _wait_until_indexed(
    client: httpx.Client,
    ingestion_url: str,
    github_repo_id: int,
    required_branches: list[str],
    *,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds

    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Timed out waiting for repo {github_repo_id} branches {required_branches}"
            )

        response = client.get(f"{ingestion_url}/status/{github_repo_id}")
        if response.status_code == 404:
            time.sleep(poll_interval_seconds)
            continue
        response.raise_for_status()

        payload = response.json()
        branch_statuses = {
            branch.get("branch_name"): str(branch.get("status", ""))
            for branch in payload.get("branches", [])
            if branch.get("branch_name")
        }
        if all(branch_statuses.get(branch) == "indexed" for branch in required_branches):
            return {branch: branch_statuses[branch] for branch in required_branches}
        if any(branch_statuses.get(branch) == "failed" for branch in required_branches):
            raise RuntimeError(f"Indexing failed for repo {github_repo_id}: {branch_statuses}")
        time.sleep(poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Index repositories for an eval dataset")
    parser.add_argument("--config", "-c", type=Path, required=True, help="Eval config YAML")
    parser.add_argument(
        "--ingestion-url",
        default="http://localhost:8001",
        help="Base URL for ingestion service",
    )
    parser.add_argument(
        "--github-token",
        default=None,
        help="GitHub token for API lookup/indexing; overrides config value",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Path to write index_registry.json (default: <dataset-path>/index_registry.json)",
    )
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve repos via GitHub API and print what would be indexed; no ingestion calls made",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    log = logging.getLogger("index_dataset")

    from lighthouse_eval.datasets.adapters import get_adapter

    config = _load_config(args.config)
    _normalize_paths(config, args.config.resolve())
    adapter_cls = get_adapter(config.dataset.adapter)
    adapter = adapter_cls()
    adapter_config = _adapter_config(config)
    if args.github_token:
        adapter_config["github_token"] = args.github_token

    log.info("Resolving repos for adapter %r ...", config.dataset.adapter)
    repos = adapter.get_repos(adapter_config)
    if not repos:
        log.warning("Adapter %s returned no repos; nothing to index.", config.dataset.adapter)
        return

    if args.dry_run:
        log.info("Dry run — would index %d repo(s):", len(repos))
        for repo in repos:
            log.info("  %s  id=%d  branches=%s", repo.full_name, repo.github_repo_id, repo.branches)
        return

    ingestion_url = args.ingestion_url.rstrip("/")
    payload = {"repositories": [repo.model_dump() for repo in repos]}
    if args.github_token:
        for repo_payload in payload["repositories"]:
            repo_payload["github_token"] = args.github_token

    with httpx.Client(timeout=60.0) as client:
        response = client.post(f"{ingestion_url}/index", json=payload)
        response.raise_for_status()
        log.info("Index request accepted for %d repositories", len(repos))

        for repo in repos:
            _wait_until_indexed(
                client,
                ingestion_url,
                repo.github_repo_id,
                repo.branches,
                poll_interval_seconds=args.poll_interval,
                timeout_seconds=args.timeout_seconds,
            )
            log.info("Indexed %s [%s]", repo.full_name, ",".join(repo.branches))

    registry = {
        repo.full_name: {
            "github_repo_id": repo.github_repo_id,
            "branch": repo.branches[0] if repo.branches else "main",
        }
        for repo in repos
    }

    output_path = args.output
    if output_path is None:
        dataset_path = config.dataset.path
        if dataset_path is None:
            raise ValueError("--output is required when dataset.path is not set in config")
        output_path = dataset_path / "index_registry.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
    log.info("Wrote index registry to %s", output_path)


if __name__ == "__main__":
    main()
