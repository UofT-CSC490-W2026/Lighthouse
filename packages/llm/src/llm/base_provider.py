from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class for LLM completion providers."""

    @abstractmethod
    def complete(self, messages: list[dict[str, str]], **kwargs) -> str:
        """Send a chat completion request and return the assistant message content."""

    @abstractmethod
    def complete_json(self, messages: list[dict[str, str]], **kwargs) -> dict:
        """Send a chat completion with JSON mode and return the parsed dict."""
