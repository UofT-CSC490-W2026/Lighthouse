from __future__ import annotations

import pytest

from eval.pricing import estimate_embedding_cost_usd, estimate_generation_cost_usd


@pytest.mark.unit
def test_estimate_generation_cost_usd_for_bedrock_model() -> None:
    cost = estimate_generation_cost_usd(
        model_name="bedrock/us.amazon.nova-pro-v1:0",
        region_name="us-east-1",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost is not None
    assert cost > 0


@pytest.mark.unit
def test_estimate_generation_cost_usd_for_openai_model() -> None:
    cost = estimate_generation_cost_usd(
        model_name="openai/gpt-5.4",
        region_name="us-east-1",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost is not None
    assert cost > 0


@pytest.mark.unit
def test_estimate_generation_cost_usd_returns_none_for_unknown_model() -> None:
    assert (
        estimate_generation_cost_usd(
            model_name="openai/does-not-exist",
            region_name="us-east-1",
            input_tokens=1000,
            output_tokens=500,
        )
        is None
    )


@pytest.mark.unit
def test_estimate_embedding_cost_usd_for_openai_embedding() -> None:
    cost = estimate_embedding_cost_usd(
        strategy="openai",
        model_name="text-embedding-3-large",
        region_name="us-east-1",
        input_tokens=2000,
    )
    assert cost is not None
    assert cost > 0
