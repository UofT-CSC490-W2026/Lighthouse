from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from ingestion.utilities.git_ops import GitOperations
from testing_utils.profiling import ProfileConfig, run_with_cprofile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile GitOperations.list_files with cProfile.")
    parser.add_argument("--directories", type=int, default=60)
    parser.add_argument("--files-per-directory", type=int, default=80)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--sort-by", default="cumtime")
    parser.add_argument("--top-n", type=int, default=40)
    parser.add_argument("--dump-prof", action="store_true")
    return parser.parse_args()


def build_repo_tree(repo_root: Path, directories: int, files_per_directory: int) -> None:
    for dir_idx in range(directories):
        target_dir = repo_root / f"pkg_{dir_idx:04d}"
        target_dir.mkdir(parents=True, exist_ok=True)

        # Majority extension set should pass list_files filters.
        for file_idx in range(files_per_directory):
            ext = ".py" if file_idx % 4 != 0 else ".ts"
            file_path = target_dir / f"file_{file_idx:04d}{ext}"
            file_path.write_text(f"# file {dir_idx}/{file_idx}\nprint('ok')\n", encoding="utf-8")

        # Add noise files that should be ignored by extension/skip logic.
        (target_dir / "package-lock.json").write_text("{}", encoding="utf-8")
        (target_dir / "notes.txt").write_text("lorem ipsum", encoding="utf-8")
        (target_dir / "Dockerfile").write_text("FROM python:3.11", encoding="utf-8")


def main() -> None:
    args = parse_args()

    with tempfile.TemporaryDirectory(prefix="lighthouse-profile-gitops-") as temp_dir:
        repo_root = Path(temp_dir) / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        build_repo_tree(repo_root, args.directories, args.files_per_directory)

        ops = GitOperations(base_dir=temp_dir)

        dump_path: Path | None = None
        if args.dump_prof:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dump_path = (
                Path(__file__).resolve().parent
                / "artifacts"
                / "git_ops"
                / f"{timestamp}.prof"
            )

        config = ProfileConfig(
            sort_by=args.sort_by,
            top_n=args.top_n,
            dump_stats_path=dump_path,
        )
        prof_result = run_with_cprofile(
            ops.list_files,
            repo_root,
            config=config,
            repeat=args.repeat,
        )

        files = prof_result.result
        print(
            "listed_files="
            f"{len(files)} repeat={args.repeat} dirs={args.directories} "
            f"files_per_dir={args.files_per_directory}"
        )
        if prof_result.dump_stats_path:
            print(f"prof_file={prof_result.dump_stats_path}")


if __name__ == "__main__":
    main()
