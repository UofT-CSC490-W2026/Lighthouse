from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GenerationResult:
    text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float


class PatchGenerator(Protocol):
    model_name: str

    def generate(self, *, system: str, user: str) -> GenerationResult: ...
