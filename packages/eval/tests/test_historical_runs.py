from __future__ import annotations

import pytest

from eval.historical_runs import (
    config_matches_summary,
    has_full_repeat_coverage,
    is_lighthouse_run_id,
    parse_run_id_segments_v2,
    rollup_lighthouse_summaries,
)


@pytest.mark.unit
def test_parse_run_id_segments_v2_lighthouse() -> None:
    rid = (
        "queued-34a813a09aaf-fam-synthetic-ab-contracts-ctx-code-chunk-ast-"
        "cg-bedrock-google-gemma-3-12b-it-em-amazon-titan-embed-text-v2-0-r01-code"
    )
    seg = parse_run_id_segments_v2(rid)
    assert seg is not None
    assert seg["family"] == "synthetic-ab-contracts"
    assert seg["context_source"] == "code"
    assert seg["chunking_strategy"] == "ast"
    assert seg["tail_context"] == "code"
    assert is_lighthouse_run_id(rid) is True


@pytest.mark.unit
def test_parse_run_id_segments_v2_baseline() -> None:
    rid = (
        "queued-34a813a09aaf-fam-synthetic-ab-contracts-ctx-code-chunk-ast-"
        "cg-bedrock-google-gemma-3-12b-it-em-amazon-titan-embed-text-v2-0-r01-baseline"
    )
    assert is_lighthouse_run_id(rid) is False


@pytest.mark.unit
def test_config_matches_summary_positive() -> None:
    rid = (
        "queued-34a813a09aaf-fam-synthetic-ab-contracts-ctx-code-chunk-ast-"
        "cg-bedrock-google-gemma-3-12b-it-em-amazon-titan-embed-text-v2-0-r01-code"
    )
    config = {
        "families": ["synthetic-ab-contracts"],
        "context_sources": ["code"],
        "chunking_strategies": ["ast"],
        "codegen_models": ["bedrock/google.gemma-3-12b-it"],
        "embedding_models": ["amazon.titan-embed-text-v2:0"],
        "embedding_strategy": "bedrock",
        "repeat_count": 1,
        "k_values": [1],
        "task_count": 30,
        "top_k": 10,
    }
    summary = {
        "family_name": "synthetic-ab-contracts",
        "run_id": rid,
        "experiment": {
            "generation_model_name_or_path": "bedrock/google.gemma-3-12b-it",
            "generation_region_name": "",
            "context_source": "code",
            "search_top_k": 10,
            "indexing_embedding": {"strategy": "bedrock", "model": "amazon.titan-embed-text-v2:0"},
            "query_embedding": {"strategy": "bedrock", "model": "amazon.titan-embed-text-v2:0"},
        },
    }
    assert config_matches_summary(config, summary) is True


@pytest.mark.unit
def test_has_full_repeat_coverage() -> None:
    summaries = [
        {"run_id": "x-r01-code"},
        {"run_id": "x-r02-code"},
        {"run_id": "x-r03-code"},
    ]
    assert has_full_repeat_coverage(summaries, repeat_count=3) is True
    assert has_full_repeat_coverage(summaries[:2], repeat_count=3) is False


@pytest.mark.unit
def test_rollup_lighthouse_summaries() -> None:
    config = {
        "families": ["synthetic-ab-contracts"],
        "context_sources": ["code"],
        "chunking_strategies": ["ast"],
        "codegen_models": ["bedrock/google.gemma-3-12b-it"],
        "embedding_models": ["amazon.titan-embed-text-v2:0"],
        "embedding_strategy": "bedrock",
        "repeat_count": 1,
        "k_values": [1],
        "task_count": 10,
        "top_k": 10,
    }
    summaries = [
        {
            "run_id": "r1",
            "total_instances": 10,
            "resolved_instances": 5,
            "efficiency": {
                "total_duration_seconds": 100.0,
                "generation": {"estimated_cost_usd": 2.5},
            },
        }
    ]
    rollup = rollup_lighthouse_summaries(summaries, config=config)
    assert rollup is not None
    assert rollup.mean_score_pct == 50.0
    assert rollup.mean_total_duration_seconds == 100.0
    assert rollup.mean_generation_cost_usd == 2.5
