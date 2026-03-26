"""Custom dataset adapter — loads local YAML-based datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lighthouse_eval.context.base import ContextProvider
from lighthouse_eval.context.static import StaticProvider
from lighthouse_eval.datasets.adapters import register
from lighthouse_eval.datasets.adapters.base import RepoInfo
from lighthouse_eval.datasets.loader import load_yaml_dataset
from lighthouse_eval.datasets.schema import Dataset
from lighthouse_eval.execution.evaluators.base import Evaluator


@register("custom")
class CustomAdapter:
    """Loads datasets from the local ``datasets/`` directory (YAML format)."""

    name = "custom"
    transform_version = "1.0.0"

    def load(self, config: dict[str, Any]) -> Dataset:
        path = config.get("path")
        if path is None:
            raise ValueError("CustomAdapter requires 'path' in dataset config")
        return load_yaml_dataset(
            Path(path),
            source_dataset=config.get("source_dataset", f"custom:{Path(path).name}"),
            transform_version=self.transform_version,
        )

    def get_evaluator(self) -> Evaluator:
        raise NotImplementedError(
            "CustomAdapter dispatches evaluators per task via resolve_evaluator"
        )

    def get_oracle_provider(self) -> ContextProvider | None:
        return StaticProvider(name="static:oracle")

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]:
        return []
