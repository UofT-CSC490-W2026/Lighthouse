from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DatasetConfig(BaseModel):
    """Which dataset to load and how."""

    adapter: str = Field(description='Adapter name, e.g. "swebench", "crosscodeeval", "bugsinpy".')
    source: str | None = Field(
        default=None,
        description="HuggingFace dataset ID, repo URL, or other source locator.",
    )
    path: Path | None = Field(
        default=None,
        description="Local path for custom datasets.",
    )
    split: str | None = None
    max_instances: int | None = Field(
        default=None,
        description="Cap the number of tasks loaded (for faster iteration).",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Adapter-specific options (e.g. libraries, splits).",
    )


class EvalConfig(BaseModel):
    """Top-level configuration for an evaluation run."""

    models: list[str] = Field(
        description='LLM model names, e.g. ["bedrock/claude-sonnet-4-20250514"].',
    )
    context_providers: list[str] = Field(
        description='Provider names, e.g. ["none", "lighthouse", "static:oracle"].',
    )
    dataset: DatasetConfig
    num_runs: int = Field(
        default=1,
        ge=1,
        description="Repetitions per (model, provider, task) triple for variance estimation.",
    )
    search_service_url: str = Field(
        default="http://localhost:8002",
        description="Base URL for the Lighthouse search service (used by LighthouseProvider).",
    )
    output_dir: Path = Field(
        default=Path("results"),
        description="Directory to write result artifacts.",
    )
    concurrency: int = Field(
        default=4,
        ge=1,
        description="Max concurrent (model, provider, task) evaluations.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
