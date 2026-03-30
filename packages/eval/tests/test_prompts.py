from __future__ import annotations

import pytest
from shared.schemas.search import WikiSnippet

from eval.prompts import build_wiki_lighthouse_user_message
from eval.slice import SWEBenchTask


@pytest.mark.unit
def test_build_wiki_lighthouse_user_message_includes_snippet_metadata() -> None:
    task = SWEBenchTask(
        instance_id="astropy__astropy-12907",
        repo="astropy/astropy",
        base_commit="abc123",
        version="4.3",
        problem_statement="Fix the failing separable model tests.",
    )
    snippets = [
        WikiSnippet(
            page_title="Modeling Overview",
            slug="modeling-overview",
            section_path="Modeling > Separable Models",
            content_snippet="Compound models should preserve separability metadata.",
            score=0.91,
        )
    ]

    message = build_wiki_lighthouse_user_message(task, snippets)

    assert "Retrieved repository wiki context from Lighthouse:" in message
    assert "Page: Modeling Overview" in message
    assert "Slug: modeling-overview" in message
    assert "Section path: Modeling > Separable Models" in message
    assert "Compound models should preserve separability metadata." in message
