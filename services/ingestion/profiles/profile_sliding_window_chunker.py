from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from ingestion.chunking.sliding_window_chunker import SlidingWindowChunker
from testing_utils.profiling import ProfileConfig, run_with_cprofile


def build_content(line_count: int) -> str:
    return "".join(f"line {idx} // payload abcdefghijklmnop\n" for idx in range(1, line_count + 1))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile SlidingWindowChunker.chunk_file with cProfile."
    )
    parser.add_argument("--line-count", type=int, default=25_000)
    parser.add_argument("--max-lines", type=int, default=200)
    parser.add_argument("--overlap-lines", type=int, default=40)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--sort-by", default="cumtime")
    parser.add_argument("--top-n", type=int, default=40)
    parser.add_argument("--dump-prof", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    chunker = SlidingWindowChunker(
        max_lines=args.max_lines,
        overlap_lines=args.overlap_lines,
    )
    content = build_content(args.line_count)

    dump_path: Path | None = None
    if args.dump_prof:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dump_path = (
            Path(__file__).resolve().parent
            / "artifacts"
            / "sliding_window_chunker"
            / f"{timestamp}.prof"
        )

    config = ProfileConfig(
        sort_by=args.sort_by,
        top_n=args.top_n,
        dump_stats_path=dump_path,
    )
    prof_result = run_with_cprofile(
        chunker.chunk_file,
        content,
        "src/sample.py",
        config=config,
        repeat=args.repeat,
    )
    chunks = prof_result.result
    print(f"generated_chunks={len(chunks)} repeat={args.repeat} line_count={args.line_count}")
    if prof_result.dump_stats_path:
        print(f"prof_file={prof_result.dump_stats_path}")


if __name__ == "__main__":
    main()
