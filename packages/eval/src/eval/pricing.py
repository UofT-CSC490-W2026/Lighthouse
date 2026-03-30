from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PRICING_DIR = Path(__file__).parent / "pricing"
_BEDROCK_PATH = _PRICING_DIR / "bedrock_pricing.json"
_OPENAI_PATH = _PRICING_DIR / "openai_pricing.json"


def estimate_generation_cost_usd(
    *,
    model_name: str,
    region_name: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    if input_tokens < 0 or output_tokens < 0:
        return None
    provider, model_id = _split_model_name(model_name)
    if provider == "bedrock":
        catalog = _load_json(_BEDROCK_PATH)
        model_data = _lookup_bedrock_model(catalog, model_id=model_id, region_name=region_name)
    elif provider == "openai":
        catalog = _load_json(_OPENAI_PATH)
        model_data = _lookup_openai_model(catalog, model_id=model_id)
    else:
        return None
    if model_data is None:
        return None
    in_rate = _as_float(model_data.get("generation_input_per_million_usd"))
    out_rate = _as_float(model_data.get("generation_output_per_million_usd"))
    if in_rate is None or out_rate is None:
        return None
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


def estimate_embedding_cost_usd(
    *,
    strategy: str,
    model_name: str,
    region_name: str,
    input_tokens: int,
) -> float | None:
    if input_tokens < 0:
        return None
    provider = strategy.strip().lower()
    if provider == "bedrock":
        catalog = _load_json(_BEDROCK_PATH)
        model_data = _lookup_bedrock_model(catalog, model_id=model_name, region_name=region_name)
    elif provider == "openai":
        catalog = _load_json(_OPENAI_PATH)
        model_data = _lookup_openai_model(catalog, model_id=model_name)
    else:
        return None
    if model_data is None:
        return None
    in_rate = _as_float(model_data.get("embedding_input_per_million_usd"))
    if in_rate is None:
        return None
    return (input_tokens / 1_000_000.0) * in_rate


def _split_model_name(model_name: str) -> tuple[str, str]:
    normalized = model_name.strip()
    if "/" not in normalized:
        return "", normalized
    provider, model_id = normalized.split("/", 1)
    return provider.lower(), model_id


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        return loaded
    return {}


def _lookup_bedrock_model(
    catalog: dict[str, Any],
    *,
    model_id: str,
    region_name: str,
) -> dict[str, Any] | None:
    models = catalog.get("models")
    if not isinstance(models, dict):
        return None
    record = models.get(model_id)
    if not isinstance(record, dict):
        return None
    regions = record.get("regions")
    if not isinstance(regions, dict):
        return None
    resolved_region = regions.get(region_name) or regions.get("*")
    if not isinstance(resolved_region, dict):
        return None
    return resolved_region


def _lookup_openai_model(catalog: dict[str, Any], *, model_id: str) -> dict[str, Any] | None:
    models = catalog.get("models")
    if not isinstance(models, dict):
        return None
    record = models.get(model_id)
    if not isinstance(record, dict):
        return None
    return record


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
