from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import uuid

from db import Chunk, DatabaseManager, IndexedFile, Repository
from search.strategies.hybrid_strategy import HybridSearchStrategy
from shared.schemas.search import SearchRequest
from testing_utils.profiling import (
    ProfileConfig,
    run_async_with_cprofile,
    run_with_cprofile,
)


@dataclass
class FakeMilvusHit:
    chunk_id: str
    score: float
    repository_id: str
    file_path: str
    branch: str
    publish_id: str


class FakeMilvusClient:
    def __init__(self, hits: list[FakeMilvusHit]) -> None:
        self.hits = hits

    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[FakeMilvusHit]:
        _ = query_embedding
        _ = filters
        return self.hits[:top_k]

    def close(self) -> None:
        return None


class FakeEmbedder:
    def embed_single(self, text: str) -> list[float]:
        _ = text
        return [0.25, 0.5, 0.75, 1.0]


class ProfileHybridSearchStrategy(HybridSearchStrategy):
    def __init__(
        self,
        db_manager: DatabaseManager,
        milvus: FakeMilvusClient,
        keyword_results: list[dict],
    ) -> None:
        super().__init__(
            db_manager=db_manager,
            milvus=milvus,
            embedder=FakeEmbedder(),
        )
        self._keyword_results = keyword_results

    def _keyword_search(self, request: SearchRequest, repo_id: str | None) -> list[dict]:
        _ = request
        _ = repo_id
        return self._keyword_results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile HybridSearchStrategy with cProfile.")
    parser.add_argument(
        "--target",
        choices=("search", "rrf", "filter", "all"),
        default="search",
    )
    parser.add_argument(
        "--size",
        choices=("small", "medium", "large"),
        default="medium",
    )
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--sort-by", default="cumtime")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--dump-prof", action="store_true")
    return parser.parse_args()


def size_config(size: str) -> tuple[int, int]:
    if size == "small":
        return 300, 50
    if size == "large":
        return 12_000, 400
    return 3_000, 120


def setup_database(database_path: Path) -> DatabaseManager:
    db = DatabaseManager(f"sqlite:///{database_path}")
    db.connect()
    db.database.create_tables([Repository, Chunk, IndexedFile])
    return db


def create_repository() -> Repository:
    suffix = uuid.uuid4().hex[:8]
    return Repository.create(
        github_repo_id=int(uuid.uuid4().int % (2**31 - 1)),
        full_name=f"owner/search-{suffix}",
        repo_url=f"https://github.com/owner/search-{suffix}",
        display_name=f"search-{suffix}",
        owner_login="owner",
        owner_type="User",
        is_private=False,
    )


def seed_chunks(
    repository: Repository,
    branch: str,
    chunk_count: int,
    changed_file_count: int,
) -> tuple[list[FakeMilvusHit], list[dict]]:
    milvus_hits: list[FakeMilvusHit] = []
    keyword_results: list[dict] = []

    with Repository._meta.database.atomic():
        for idx in range(chunk_count):
            file_path = f"src/file_{idx % max(1, changed_file_count):04d}.py"
            chunk_id = str(uuid.uuid4())
            publish_id = "batch-current" if idx % 5 != 0 else "legacy"

            Chunk.create(
                id=chunk_id,
                repository=repository.id,
                branch=branch,
                file_path=file_path,
                start_line=1,
                end_line=10,
                content=f"def f_{idx}():\n    return {idx}\n",
                language="python",
                chunk_hash=uuid.uuid4().hex,
                publish_id=publish_id,
            )
            milvus_hits.append(
                FakeMilvusHit(
                    chunk_id=chunk_id,
                    score=1.0 - (idx / max(1, chunk_count)),
                    repository_id=repository.id,
                    file_path=file_path,
                    branch=branch,
                    publish_id=publish_id,
                )
            )

            if idx % 2 == 0:
                keyword_results.append({"chunk_id": chunk_id, "score": 1.0 / (idx + 1)})

    active_files = {f"src/file_{i:04d}.py" for i in range(changed_file_count)}
    for file_path in active_files:
        IndexedFile.create(
            repository=repository.id,
            branch_name=branch,
            file_path=file_path,
            active_publish_id="batch-current",
        )

    return milvus_hits, keyword_results


def maybe_dump_path(enabled: bool, target: str, size: str) -> Path | None:
    if not enabled:
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{target}_{size}_{timestamp}.prof"
    return Path(__file__).resolve().parent / "artifacts" / "hybrid_strategy" / filename


def run_search_profile(strategy: ProfileHybridSearchStrategy, repeat: int, cfg: ProfileConfig) -> None:
    repo = Repository.select().first()
    if repo is None:
        raise RuntimeError("Repository seed failed before search profiling.")
    req = SearchRequest(
        query="find auth and token flow",
        github_repo_id=repo.github_repo_id,
        branch="main",
        top_k=20,
    )
    result = run_async_with_cprofile(
        strategy.search,
        req,
        config=cfg,
        repeat=repeat,
    )
    print(f"search_snippets={len(result.result.snippets)} total_results={result.result.total_results}")


def run_rrf_profile(vector_count: int, keyword_count: int, repeat: int, cfg: ProfileConfig) -> None:
    vector = [{"chunk_id": f"v_{i}", "score": 1.0 / (i + 1)} for i in range(vector_count)]
    keyword = [{"chunk_id": f"k_{i}", "score": 1.0 / (i + 1)} for i in range(keyword_count)]
    result = run_with_cprofile(
        HybridSearchStrategy._rrf_fusion,
        vector,
        keyword,
        config=cfg,
        repeat=repeat,
    )
    print(f"rrf_results={len(result.result)} vector={vector_count} keyword={keyword_count}")


def run_filter_profile(strategy: HybridSearchStrategy, vector_count: int, repeat: int, cfg: ProfileConfig) -> None:
    vector_results = []
    active_map = {}
    for idx in range(vector_count):
        file_path = f"src/filter_{idx % 300:04d}.py"
        key = ("repo-1", "main", file_path)
        active_map[key] = "batch-current" if idx % 3 != 0 else None
        vector_results.append(
            {
                "chunk_id": f"c_{idx}",
                "repository_id": "repo-1",
                "branch": "main",
                "file_path": file_path,
                "publish_id": "batch-current" if idx % 2 == 0 else "legacy",
                "score": 0.9,
            }
        )
    strategy._get_active_publish_map = lambda _: active_map  # type: ignore[method-assign]
    result = run_with_cprofile(
        strategy._filter_vector_results,
        vector_results,
        config=cfg,
        repeat=repeat,
    )
    print(f"filtered_results={len(result.result)} source_results={len(vector_results)}")


def main() -> None:
    args = parse_args()
    chunk_count, changed_file_count = size_config(args.size)
    with tempfile.TemporaryDirectory(prefix="lighthouse-profile-hybrid-strategy-") as tmp_dir:
        db_path = Path(tmp_dir) / "profile_hybrid_strategy.db"
        db = setup_database(db_path)

        try:
            repo = create_repository()
            branch = "main"
            milvus_hits, keyword_results = seed_chunks(repo, branch, chunk_count, changed_file_count)
            strategy = ProfileHybridSearchStrategy(
                db_manager=db,
                milvus=FakeMilvusClient(milvus_hits),
                keyword_results=keyword_results,
            )

            targets = [args.target] if args.target != "all" else ["search", "rrf", "filter"]
            for target in targets:
                cfg = ProfileConfig(
                    sort_by=args.sort_by,
                    top_n=args.top_n,
                    dump_stats_path=maybe_dump_path(args.dump_prof, target, args.size),
                )
                print(f"--- target={target} size={args.size} repeat={args.repeat} ---")
                if target == "search":
                    run_search_profile(strategy, args.repeat, cfg)
                elif target == "rrf":
                    run_rrf_profile(chunk_count // 2, chunk_count // 3, args.repeat, cfg)
                else:
                    run_filter_profile(strategy, chunk_count, args.repeat, cfg)
                if cfg.dump_stats_path:
                    print(f"prof_file={cfg.dump_stats_path}")
        finally:
            db.close()


if __name__ == "__main__":
    main()
