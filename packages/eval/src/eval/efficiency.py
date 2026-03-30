from __future__ import annotations

from dataclasses import asdict, dataclass

from eval.pricing import estimate_generation_cost_usd


@dataclass(frozen=True)
class GenerationCallMetrics:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float


@dataclass(frozen=True)
class GenerationAggregateMetrics:
    request_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms_total: float
    latency_ms_avg: float
    estimated_cost_usd: float | None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RunEfficiencySummary:
    generation: GenerationAggregateMetrics
    indexing_duration_seconds: float
    wiki_duration_seconds: float
    retrieval_duration_seconds: float
    generation_duration_seconds: float
    total_duration_seconds: float
    retrieval_request_count: int
    retrieval_query_tokens_estimate: int | None = None
    retrieval_query_cost_estimate_usd: float | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def aggregate_generation_metrics(
    *,
    calls: tuple[GenerationCallMetrics, ...],
    model_name: str,
    region_name: str,
) -> GenerationAggregateMetrics:
    request_count = len(calls)
    input_tokens = sum(call.input_tokens for call in calls)
    output_tokens = sum(call.output_tokens for call in calls)
    total_tokens = sum(call.total_tokens for call in calls)
    latency_total = sum(call.latency_ms for call in calls)
    latency_avg = latency_total / request_count if request_count else 0.0
    estimated_cost_usd = estimate_generation_cost_usd(
        model_name=model_name,
        region_name=region_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return GenerationAggregateMetrics(
        request_count=request_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        latency_ms_total=latency_total,
        latency_ms_avg=latency_avg,
        estimated_cost_usd=estimated_cost_usd,
    )
