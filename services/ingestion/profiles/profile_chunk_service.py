from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import uuid

from db import Chunk, DatabaseManager, IndexedFile, Repository, StagingChunk
from ingestion.utilities.services.chunk import ChunkService
from testing_utils.profiling import ProfileConfig, run_with_cprofile


class FakeMilvusClient:
    def __init__(self) -> None:
        self.insert_calls = 0
        self.delete_calls = 0

    def insert(self, records: list[dict]) -> None:
        self.insert_calls += len(records)

    def delete_by_filter(self, expr: str) -> None:
        _ = expr
        self.delete_calls += 1

    def close(self) -> None:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile ChunkService methods with cProfile.")
    parser.add_argument(
        "--target",
        choices=("write_staging", "write_embeddings", "move_to_final", "publish_incremental"),
        default="move_to_final",
    )
    parser.add_argument("--chunk-count", type=int, default=8_000)
    parser.add_argument("--changed-files", type=int, default=120)
    parser.add_argument("--embedding-dim", type=int, default=64)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--sort-by", default="cumtime")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--dump-prof", action="store_true")
    return parser.parse_args()


def setup_database(database_path: Path) -> DatabaseManager:
    db = DatabaseManager(f"sqlite:///{database_path}")
    db.connect()
    db.database.create_tables([Repository, Chunk, IndexedFile, StagingChunk])
    return db


def create_repository() -> Repository:
    suffix = uuid.uuid4().hex[:8]
    return Repository.create(
        github_repo_id=int(uuid.uuid4().int % (2**31 - 1)),
        full_name=f"owner/repo-{suffix}",
        repo_url=f"https://github.com/owner/repo-{suffix}",
        display_name=f"repo-{suffix}",
        owner_login="owner",
        owner_type="User",
        is_private=False,
    )


def make_chunk_records(
    repository_id: str,
    branch: str,
    count: int,
    file_span: int,
) -> list[dict]:
    records: list[dict] = []
    safe_span = max(1, file_span)
    for idx in range(count):
        file_index = idx % safe_span
        file_path = f"src/module_{file_index:04d}.py"
        content = (
            "def f(x):\n"
            f"    return x + {idx}\n"
            f"# payload {idx:08d}\n"
        )
        records.append(
            {
                "chunk_id": str(uuid.uuid4()),
                "repository_id": repository_id,
                "branch": branch,
                "file_path": file_path,
                "start_line": 1,
                "end_line": 3,
                "content": content,
                "language": "python",
                "chunk_hash": uuid.uuid4().hex,
            }
        )
    return records


def stage_chunks(
    svc: ChunkService,
    batch_id: str,
    chunks: list[dict],
    embedding_dim: int,
) -> None:
    svc.write_staging(batch_id, chunks)
    embeddings = [[float(i % 11) / 10.0 for i in range(embedding_dim)] for _ in chunks]
    svc.write_staging_embeddings(batch_id, 0, embeddings)


def maybe_dump_path(enabled: bool, script_name: str) -> Path | None:
    if not enabled:
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(__file__).resolve().parent / "artifacts" / script_name / f"{timestamp}.prof"


def main() -> None:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="lighthouse-profile-chunk-service-") as tmp_dir:
        db_path = Path(tmp_dir) / "profile_chunk_service.db"
        db = setup_database(db_path)
        milvus = FakeMilvusClient()
        svc = ChunkService(db, milvus)
        repo = create_repository()
        branch = "main"

        try:
            config = ProfileConfig(
                sort_by=args.sort_by,
                top_n=args.top_n,
                dump_stats_path=maybe_dump_path(args.dump_prof, "chunk_service"),
            )

            if args.target == "write_staging":
                batch_id = str(uuid.uuid4())
                chunks = make_chunk_records(repo.id, branch, args.chunk_count, args.changed_files)
                result = run_with_cprofile(
                    svc.write_staging,
                    batch_id,
                    chunks,
                    config=config,
                    repeat=args.repeat,
                )
                print(f"written={result.result} target={args.target}")

            elif args.target == "write_embeddings":
                batch_id = str(uuid.uuid4())
                chunks = make_chunk_records(repo.id, branch, args.chunk_count, args.changed_files)
                svc.write_staging(batch_id, chunks)
                embeddings = [
                    [float(i % 17) / 10.0 for i in range(args.embedding_dim)]
                    for _ in range(args.chunk_count)
                ]
                result = run_with_cprofile(
                    svc.write_staging_embeddings,
                    batch_id,
                    0,
                    embeddings,
                    config=config,
                    repeat=args.repeat,
                )
                print(
                    f"updated_embeddings={len(embeddings)} "
                    f"target={args.target} result={result.result}"
                )

            elif args.target == "move_to_final":
                batch_id = str(uuid.uuid4())
                chunks = make_chunk_records(repo.id, branch, args.chunk_count, args.changed_files)
                stage_chunks(svc, batch_id, chunks, args.embedding_dim)
                result = run_with_cprofile(
                    svc.move_to_final,
                    batch_id,
                    config=config,
                    repeat=args.repeat,
                )
                with db.connection_context():
                    final_count = Chunk.select().count()
                print(
                    f"moved={result.result} final_count={final_count} "
                    f"milvus_inserted={milvus.insert_calls} target={args.target}"
                )

            else:
                batch_id = str(uuid.uuid4())
                chunks = make_chunk_records(repo.id, branch, args.chunk_count, args.changed_files)
                stage_chunks(svc, batch_id, chunks, args.embedding_dim)
                changed_files = [f"src/module_{i:04d}.py" for i in range(args.changed_files)]
                result = run_with_cprofile(
                    svc.publish_incremental_batch,
                    batch_id,
                    repo.id,
                    branch,
                    changed_files,
                    config=config,
                    repeat=args.repeat,
                )
                print(
                    "cleanup_targets="
                    f"{len(result.result)} changed_files={len(changed_files)} "
                    f"milvus_inserted={milvus.insert_calls} target={args.target}"
                )

            if config.dump_stats_path:
                print(f"prof_file={config.dump_stats_path}")

            # Keep one tiny read to ensure tables were touched and avoid dead-code style usage.
            with db.connection_context():
                _ = json.dumps({"staging_rows": StagingChunk.select().count()})
        finally:
            db.close()


if __name__ == "__main__":
    main()
