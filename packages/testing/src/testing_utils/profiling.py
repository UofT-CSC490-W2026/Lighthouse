from __future__ import annotations

import asyncio
import cProfile
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
import pstats
from typing import Any, Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


@dataclass(slots=True)
class ProfileConfig:
    sort_by: str = "cumtime"
    top_n: int = 40
    strip_dirs: bool = True
    print_stats: bool = True
    dump_stats_path: str | Path | None = None


@dataclass(slots=True)
class ProfileRunResult:
    result: Any
    profiler: cProfile.Profile
    dump_stats_path: Path | None


def _build_stats(profiler: cProfile.Profile, config: ProfileConfig) -> pstats.Stats:
    stats = pstats.Stats(profiler)
    if config.strip_dirs:
        stats.strip_dirs()
    stats.sort_stats(config.sort_by)
    return stats


def _maybe_dump(profiler: cProfile.Profile, config: ProfileConfig) -> Path | None:
    if config.dump_stats_path is None:
        return None

    out_path = Path(config.dump_stats_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profiler.dump_stats(str(out_path))
    return out_path


def _maybe_print(profiler: cProfile.Profile, config: ProfileConfig) -> None:
    if not config.print_stats:
        return
    stats = _build_stats(profiler, config)
    stats.print_stats(config.top_n)


def run_with_cprofile(
    fn: Callable[P, R],
    *args: P.args,
    config: ProfileConfig | None = None,
    repeat: int = 1,
    **kwargs: P.kwargs,
) -> ProfileRunResult:
    cfg = config or ProfileConfig()
    profiler = cProfile.Profile()
    result: R | None = None

    profiler.enable()
    try:
        for _ in range(max(1, repeat)):
            result = fn(*args, **kwargs)
    finally:
        profiler.disable()

    _maybe_print(profiler, cfg)
    dump_path = _maybe_dump(profiler, cfg)
    return ProfileRunResult(result=result, profiler=profiler, dump_stats_path=dump_path)


def run_async_with_cprofile(
    coro_fn: Callable[P, Any],
    *args: P.args,
    config: ProfileConfig | None = None,
    repeat: int = 1,
    **kwargs: P.kwargs,
) -> ProfileRunResult:
    cfg = config or ProfileConfig()

    async def _runner() -> Any:
        last_result: Any = None
        for _ in range(max(1, repeat)):
            last_result = await coro_fn(*args, **kwargs)
        return last_result

    profiler = cProfile.Profile()
    profiler.enable()
    try:
        result = asyncio.run(_runner())
    finally:
        profiler.disable()

    _maybe_print(profiler, cfg)
    dump_path = _maybe_dump(profiler, cfg)
    return ProfileRunResult(result=result, profiler=profiler, dump_stats_path=dump_path)


def profiled(
    *,
    config: ProfileConfig | None = None,
    repeat: int = 1,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            prof_result = run_with_cprofile(
                fn,
                *args,
                config=config,
                repeat=repeat,
                **kwargs,
            )
            return prof_result.result

        return wrapper

    return decorator


def profiled_async(
    *,
    config: ProfileConfig | None = None,
    repeat: int = 1,
) -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    def decorator(fn: Callable[P, Any]) -> Callable[P, Any]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            async def _call_once() -> Any:
                return await fn(*args, **kwargs)

            # Keep async interface while still using one cProfile session.
            cfg = config or ProfileConfig()
            profiler = cProfile.Profile()
            profiler.enable()
            try:
                result: Any = None
                for _ in range(max(1, repeat)):
                    result = await _call_once()
            finally:
                profiler.disable()
            _maybe_print(profiler, cfg)
            _maybe_dump(profiler, cfg)
            return result

        return wrapper

    return decorator


@contextmanager
def profile_block(config: ProfileConfig | None = None):
    cfg = config or ProfileConfig()
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        yield profiler
    finally:
        profiler.disable()
        _maybe_print(profiler, cfg)
        _maybe_dump(profiler, cfg)
