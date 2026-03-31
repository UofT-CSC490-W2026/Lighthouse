"""Helpers for matching synthetic run summaries to singleton matrix configs."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

_SAFE_SLUG_RE = re.compile(r"[^a-z0-9]+")

_RUN_CHUNK_RE = re.compile(r"-chunk-(.+?)-cg-")
_RUN_CTX_RE = re.compile(r"-fam-(.+?)-ctx-")
_RUN_CG_RE = re.compile(r"-cg-(.+?)-em-")
_RUN_EM_RE = re.compile(r"-em-(.+?)-r(\d{2})-")
_RUN_TAIL_RE = re.compile(r"-r(\d{2})-([^-]+)$")


def matrix_slug(value: str) -> str:
    compact = _SAFE_SLUG_RE.sub("-", value.lower()).strip("-")
    return compact or "x"


def parse_run_id_segments_v2(run_id: str) -> dict[str, str] | None:
    chunk_m = _RUN_CHUNK_RE.search(run_id)
    ctx_m = _RUN_CTX_RE.search(run_id)
    cg_m = _RUN_CG_RE.search(run_id)
    em_m = _RUN_EM_RE.search(run_id)
    tail_m = _RUN_TAIL_RE.search(run_id)
    if not (chunk_m and ctx_m and cg_m and em_m and tail_m):
        return None
    family = ctx_m.group(1)
    rest = run_id[ctx_m.end(0) :]
    parts = rest.split("-chunk-", 1)
    if len(parts) != 2:
        return None
    context_source = parts[0]
    return {
        "family": family,
        "context_source": context_source,
        "chunking_strategy": chunk_m.group(1),
        "codegen_model": cg_m.group(1),
        "embedding_model": em_m.group(1),
        "repeat": em_m.group(2),
        "tail_context": tail_m.group(2),
    }


def is_lighthouse_run_id(run_id: str) -> bool:
    tail_m = _RUN_TAIL_RE.search(run_id)
    if tail_m is None:
        return False
    return tail_m.group(2) != "baseline"


def load_run_id_list(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return tuple(lines)


def read_summary(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _singleton_list(config: Mapping[str, Any], key: str) -> str:
    values = config.get(key)
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError(f"{key} must be a singleton list")
    return str(values[0])


def config_matches_summary(config: Mapping[str, Any], summary: Mapping[str, Any]) -> bool:
    """True if a summary.json belongs to this singleton matrix config (lighthouse cell)."""
    family = _singleton_list(config, "families")
    ctx = _singleton_list(config, "context_sources")
    chunk = _singleton_list(config, "chunking_strategies")
    cg = _singleton_list(config, "codegen_models")
    em = _singleton_list(config, "embedding_models")
    emb_strat = str(config.get("embedding_strategy", "")).strip()

    if str(summary.get("family_name", "")).strip() != family:
        return False

    experiment = summary.get("experiment")
    if not isinstance(experiment, dict):
        return False

    if str(experiment.get("generation_model_name_or_path", "")).strip() != cg:
        return False
    if str(experiment.get("context_source", "")).strip() != ctx:
        return False

    indexing = experiment.get("indexing_embedding")
    if not isinstance(indexing, dict):
        return False
    if str(indexing.get("strategy", "")).strip() != emb_strat:
        return False
    if str(indexing.get("model", "")).strip() != em:
        return False

    run_id = str(summary.get("run_id", ""))
    segments = parse_run_id_segments_v2(run_id)
    if segments is None:
        return False
    if segments["family"] != matrix_slug(family):
        return False
    if segments["context_source"] != matrix_slug(ctx):
        return False
    if segments["chunking_strategy"] != matrix_slug(chunk):
        return False
    if segments["codegen_model"] != matrix_slug(cg):
        return False
    if segments["embedding_model"] != matrix_slug(em):
        return False
    if not is_lighthouse_run_id(run_id):
        return False
    if segments["tail_context"] != matrix_slug(ctx):
        return False
    return True


def list_completed_lighthouse_summaries(
    *,
    run_ids: tuple[str, ...],
    runs_root: Path,
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return summary payloads for listed run ids that match the config (lighthouse only)."""
    matched: list[dict[str, Any]] = []
    for run_id in run_ids:
        rid = run_id.strip()
        if not rid:
            continue
        summary = read_summary(runs_root / rid / "summary.json")
        if summary is None:
            continue
        if config_matches_summary(config, summary):
            matched.append(summary)
    return matched


def lighthouse_repeat_indices(summaries: Sequence[dict[str, Any]]) -> set[int]:
    repeats: set[int] = set()
    for summary in summaries:
        run_id = str(summary.get("run_id", ""))
        tail_m = _RUN_TAIL_RE.search(run_id)
        if tail_m is None:
            continue
        repeats.add(int(tail_m.group(1)))
    return repeats


def has_full_repeat_coverage(summaries: Sequence[dict[str, Any]], *, repeat_count: int) -> bool:
    if repeat_count < 1:
        return False
    return lighthouse_repeat_indices(summaries).issuperset(set(range(1, repeat_count + 1)))


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    return None


@dataclass(frozen=True)
class HistoricalCellRollup:
    family: str
    context_source: str
    chunking_strategy: str
    codegen_model: str
    embedding_strategy: str
    embedding_model: str
    repeat_count: int
    task_count: int
    top_k: int
    k_values: tuple[int, ...]
    mean_score_pct: float
    mean_total_duration_seconds: float
    mean_generation_cost_usd: float | None
    provenance_run_ids: tuple[str, ...]


def rollup_lighthouse_summaries(
    summaries: Sequence[dict[str, Any]],
    *,
    config: Mapping[str, Any],
) -> HistoricalCellRollup | None:
    """Aggregate lighthouse summaries for one config (same cell, multiple repeats)."""
    if not summaries:
        return None

    family = _singleton_list(config, "families")
    ctx = _singleton_list(config, "context_sources")
    chunk = _singleton_list(config, "chunking_strategies")
    cg = _singleton_list(config, "codegen_models")
    em = _singleton_list(config, "embedding_models")
    emb_strat = str(config.get("embedding_strategy", "")).strip()
    repeat_count = int(config["repeat_count"])
    task_count = int(config["task_count"])
    top_k = int(config["top_k"])
    k_values = tuple(int(x) for x in config["k_values"])

    scores: list[float] = []
    durs: list[float] = []
    costs: list[float] = []
    run_ids: list[str] = []

    for summary in summaries:
        total = int(summary.get("total_instances", summary.get("total_tasks", 0)))
        resolved = int(summary.get("resolved_instances", summary.get("resolved_tasks", 0)))
        if total <= 0:
            continue
        scores.append(100.0 * resolved / total)

        efficiency = summary.get("efficiency")
        dur: float | None = None
        cost: float | None = None
        if isinstance(efficiency, dict):
            dur = _finite_number(efficiency.get("total_duration_seconds"))
            gen = efficiency.get("generation")
            if isinstance(gen, dict):
                cost = _finite_number(gen.get("estimated_cost_usd"))

        if dur is None:
            continue
        durs.append(dur)
        if cost is not None:
            costs.append(cost)
        rid = str(summary.get("run_id", "")).strip()
        if rid:
            run_ids.append(rid)

    if not scores or not durs:
        return None

    mean_score = sum(scores) / len(scores)
    mean_dur = sum(durs) / len(durs)
    mean_cost: float | None
    if costs:
        mean_cost = sum(costs) / len(costs)
    else:
        mean_cost = None

    return HistoricalCellRollup(
        family=family,
        context_source=ctx,
        chunking_strategy=chunk,
        codegen_model=cg,
        embedding_strategy=emb_strat,
        embedding_model=em,
        repeat_count=repeat_count,
        task_count=task_count,
        top_k=top_k,
        k_values=k_values,
        mean_score_pct=mean_score,
        mean_total_duration_seconds=mean_dur,
        mean_generation_cost_usd=mean_cost,
        provenance_run_ids=tuple(sorted(set(run_ids))),
    )
