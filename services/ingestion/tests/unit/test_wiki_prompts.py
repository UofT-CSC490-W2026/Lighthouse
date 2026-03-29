from __future__ import annotations

import pytest

from ingestion.wiki.prompts import build_page_prompt, build_structure_prompt


@pytest.mark.unit
class TestBuildStructurePrompt:
    def test_returns_two_messages(self) -> None:
        messages = build_structure_prompt(
            file_paths=["src/main.py", "src/utils.py"],
            sample_chunks=["def main(): pass"],
            repo_name="owner/repo",
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_includes_repo_name(self) -> None:
        messages = build_structure_prompt(
            file_paths=["a.py"],
            sample_chunks=[],
            repo_name="owner/repo",
        )
        assert "owner/repo" in messages[1]["content"]

    def test_includes_file_paths(self) -> None:
        messages = build_structure_prompt(
            file_paths=["src/main.py", "src/utils.py"],
            sample_chunks=[],
            repo_name="owner/repo",
        )
        assert "src/main.py" in messages[1]["content"]
        assert "src/utils.py" in messages[1]["content"]

    def test_includes_sample_chunks(self) -> None:
        messages = build_structure_prompt(
            file_paths=["a.py"],
            sample_chunks=["chunk content here"],
            repo_name="owner/repo",
        )
        assert "chunk content here" in messages[1]["content"]


@pytest.mark.unit
class TestBuildPagePrompt:
    def test_returns_two_messages(self) -> None:
        messages = build_page_prompt(
            page_title="Overview",
            page_description="High-level overview of the project.",
            context_chunks=["def foo(): pass"],
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_includes_title_and_description(self) -> None:
        messages = build_page_prompt(
            page_title="Overview",
            page_description="High-level overview.",
            context_chunks=[],
        )
        assert "Overview" in messages[1]["content"]
        assert "High-level overview." in messages[1]["content"]

    def test_includes_context_chunks(self) -> None:
        messages = build_page_prompt(
            page_title="Overview",
            page_description="desc",
            context_chunks=["chunk A", "chunk B"],
        )
        assert "chunk A" in messages[1]["content"]
        assert "chunk B" in messages[1]["content"]

    def test_empty_context_shows_fallback(self) -> None:
        messages = build_page_prompt(
            page_title="Overview",
            page_description="desc",
            context_chunks=[],
        )
        assert "No code context available" in messages[1]["content"]
