from __future__ import annotations

from llm import LLMProvider


class MockLLMProvider(LLMProvider):
    """Returns deterministic responses for testing. No external API calls."""

    def __init__(self, **kwargs) -> None:
        self.call_count = 0
        self.last_messages: list[dict[str, str]] = []

    def complete(self, messages: list[dict[str, str]], **kwargs) -> str:
        self.call_count += 1
        self.last_messages = messages
        return "# Mock Wiki Page\n\nThis is mock-generated content."

    def complete_json(self, messages: list[dict[str, str]], **kwargs) -> dict:
        self.call_count += 1
        self.last_messages = messages
        return {
            "title": "Mock Wiki",
            "description": "Auto-generated mock wiki.",
            "sections": [
                {
                    "title": "Overview",
                    "slug": "overview",
                    "pages": [
                        {
                            "title": "Getting Started",
                            "slug": "getting-started",
                            "description": "How to get started with the project.",
                            "source_file_hints": ["README.md"],
                        }
                    ],
                    "subsections": [],
                }
            ],
        }
