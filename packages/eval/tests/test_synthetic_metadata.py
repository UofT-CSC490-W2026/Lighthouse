from __future__ import annotations

from pathlib import Path

import pytest

from eval.synthetic.metadata import resolve_synthetic_experiment_metadata


@pytest.mark.unit
def test_resolve_synthetic_experiment_metadata_uses_env_defaults(tmp_path: Path) -> None:
    ingestion_env = tmp_path / "services" / "ingestion" / ".env"
    search_env = tmp_path / "services" / "search" / ".env"
    ingestion_env.parent.mkdir(parents=True, exist_ok=True)
    search_env.parent.mkdir(parents=True, exist_ok=True)
    ingestion_env.write_text("EMBEDDING_STRATEGY=bedrock\n", encoding="utf-8")
    search_env.write_text("EMBEDDING_STRATEGY=openai\n", encoding="utf-8")

    metadata = resolve_synthetic_experiment_metadata(
        generation_model_name_or_path="bedrock/us.amazon.nova-pro-v1:0",
        generation_region_name="us-east-1",
        context_source="code",
        search_top_k=3,
        repo_root=tmp_path,
    )

    assert metadata.generation_model_name_or_path == "bedrock/us.amazon.nova-pro-v1:0"
    assert metadata.generation_region_name == "us-east-1"
    assert metadata.indexing_embedding.strategy == "bedrock"
    assert metadata.indexing_embedding.model == "amazon.titan-embed-text-v2:0"
    assert metadata.query_embedding.strategy == "openai"
    assert metadata.query_embedding.model == "text-embedding-3-large"
    assert metadata.context_source == "code"
    assert metadata.search_top_k == 3
