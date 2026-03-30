from __future__ import annotations

from apikit.builders import build_csv_row, build_url
from apikit.transforms import flatten_dict, snake_to_camel


def api_endpoint(host: str, version: int, resource: str) -> str:
    return build_url("https", host, f"/api/v{version}/{resource}")


def export_row(record: dict) -> str:
    flat = flatten_dict(record)
    return build_csv_row([str(v) for v in flat.values()])


def camel_keys(data: dict[str, object]) -> dict[str, object]:
    return {snake_to_camel(k): v for k, v in data.items()}
