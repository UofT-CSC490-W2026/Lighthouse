from __future__ import annotations

from typing import Protocol


class PatchGenerator(Protocol):
    model_name: str

    def generate_text(self, *, system: str, user: str) -> str: ...
