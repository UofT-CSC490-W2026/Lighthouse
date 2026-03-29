from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from shared.config import DEFAULT_EMBEDDING_STRATEGY, default_embedding_model


DEFAULT_INGESTION_ENV_PATH = Path("services/ingestion/.env")
DEFAULT_SEARCH_ENV_PATH = Path("services/search/.env")


@dataclass(frozen=True)
class SyntheticEmbeddingConfig:
    strategy: str
    model: str


@dataclass(frozen=True)
class SyntheticExperimentMetadata:
    generation_model_name_or_path: str
    generation_region_name: str
    indexing_embedding: SyntheticEmbeddingConfig
    query_embedding: SyntheticEmbeddingConfig
    context_source: str
    search_top_k: int | None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def empty_synthetic_experiment_metadata() -> SyntheticExperimentMetadata:
    return SyntheticExperimentMetadata(
        generation_model_name_or_path="",
        generation_region_name="",
        indexing_embedding=SyntheticEmbeddingConfig(strategy="", model=""),
        query_embedding=SyntheticEmbeddingConfig(strategy="", model=""),
        context_source="",
        search_top_k=None,
    )


def resolve_synthetic_experiment_metadata(
    *,
    generation_model_name_or_path: str,
    generation_region_name: str,
    context_source: str,
    search_top_k: int | None = None,
    indexing_embedding_strategy: str | None = None,
    indexing_embedding_model: str | None = None,
    query_embedding_strategy: str | None = None,
    query_embedding_model: str | None = None,
    repo_root: Path | None = None,
) -> SyntheticExperimentMetadata:
    resolved_repo_root = (repo_root or Path.cwd()).resolve()
    ingestion_env = _load_env_file(_resolve_env_path(resolved_repo_root, DEFAULT_INGESTION_ENV_PATH))
    search_env = _load_env_file(_resolve_env_path(resolved_repo_root, DEFAULT_SEARCH_ENV_PATH))

    indexing = SyntheticEmbeddingConfig(
        strategy=_resolve_embedding_strategy(indexing_embedding_strategy, ingestion_env),
        model="",
    )
    indexing = SyntheticEmbeddingConfig(
        strategy=indexing.strategy,
        model=_resolve_embedding_model(indexing_embedding_model, indexing.strategy, ingestion_env),
    )

    query = SyntheticEmbeddingConfig(
        strategy=_resolve_embedding_strategy(query_embedding_strategy, search_env),
        model="",
    )
    query = SyntheticEmbeddingConfig(
        strategy=query.strategy,
        model=_resolve_embedding_model(query_embedding_model, query.strategy, search_env),
    )

    return SyntheticExperimentMetadata(
        generation_model_name_or_path=generation_model_name_or_path.strip(),
        generation_region_name=generation_region_name.strip(),
        indexing_embedding=indexing,
        query_embedding=query,
        context_source=context_source.strip(),
        search_top_k=search_top_k,
    )


def synthetic_experiment_metadata_from_json(data: dict[str, object]) -> SyntheticExperimentMetadata:
    experiment = data.get("experiment", {})
    if not isinstance(experiment, dict):
        return empty_synthetic_experiment_metadata()
    experiment_map = cast(dict[str, object], experiment)
    indexing = experiment_map.get("indexing_embedding", {})
    if not isinstance(indexing, dict):
        indexing = {}
    indexing_map = cast(dict[str, object], indexing)
    query = experiment_map.get("query_embedding", {})
    if not isinstance(query, dict):
        query = {}
    query_map = cast(dict[str, object], query)
    search_top_k = experiment_map.get("search_top_k")
    return SyntheticExperimentMetadata(
        generation_model_name_or_path=str(
            experiment_map.get("generation_model_name_or_path", "")
        ).strip(),
        generation_region_name=str(experiment_map.get("generation_region_name", "")).strip(),
        indexing_embedding=SyntheticEmbeddingConfig(
            strategy=str(indexing_map.get("strategy", "")).strip(),
            model=str(indexing_map.get("model", "")).strip(),
        ),
        query_embedding=SyntheticEmbeddingConfig(
            strategy=str(query_map.get("strategy", "")).strip(),
            model=str(query_map.get("model", "")).strip(),
        ),
        context_source=str(experiment_map.get("context_source", "")).strip(),
        search_top_k=search_top_k if isinstance(search_top_k, int) else None,
    )


def _resolve_env_path(repo_root: Path, relative_path: Path) -> Path | None:
    primary = repo_root / relative_path
    if primary.is_file():
        return primary
    fallback = primary.with_name(primary.name + ".example")
    if fallback.is_file():
        return fallback
    return None


def _load_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _resolve_embedding_strategy(override: str | None, env_values: dict[str, str]) -> str:
    strategy = (override or env_values.get("EMBEDDING_STRATEGY") or DEFAULT_EMBEDDING_STRATEGY).strip()
    return strategy or DEFAULT_EMBEDDING_STRATEGY


def _resolve_embedding_model(
    override: str | None,
    strategy: str,
    env_values: dict[str, str],
) -> str:
    explicit_model = (override or env_values.get("EMBEDDING_MODEL") or "").strip()
    if explicit_model:
        return explicit_model
    try:
        return default_embedding_model(strategy)
    except ValueError:
        return ""
