from __future__ import annotations

import pytest

from ingestion.temporal.activities.wiki import _flatten_structure_pages


@pytest.mark.unit
class TestFlattenStructurePages:
    def test_empty_structure(self) -> None:
        assert _flatten_structure_pages({"sections": []}) == []

    def test_single_section_single_page(self) -> None:
        structure = {
            "sections": [
                {
                    "slug": "overview",
                    "pages": [
                        {
                            "slug": "intro",
                            "title": "Introduction",
                            "description": "Getting started.",
                            "source_file_hints": ["README.md"],
                        }
                    ],
                    "subsections": [],
                }
            ]
        }
        pages = _flatten_structure_pages(structure)
        assert len(pages) == 1
        assert pages[0]["slug"] == "intro"
        assert pages[0]["title"] == "Introduction"
        assert pages[0]["section_path"] == "overview"
        assert pages[0]["source_file_hints"] == ["README.md"]

    def test_nested_subsections(self) -> None:
        structure = {
            "sections": [
                {
                    "slug": "architecture",
                    "pages": [
                        {"slug": "top-page", "title": "Top", "description": "d"},
                    ],
                    "subsections": [
                        {
                            "slug": "services",
                            "pages": [
                                {"slug": "ingestion", "title": "Ingestion", "description": "d"},
                            ],
                            "subsections": [],
                        }
                    ],
                }
            ]
        }
        pages = _flatten_structure_pages(structure)
        assert len(pages) == 2
        assert pages[0]["section_path"] == "architecture"
        assert pages[1]["section_path"] == "architecture/services"

    def test_multiple_sections(self) -> None:
        structure = {
            "sections": [
                {
                    "slug": "sec-a",
                    "pages": [{"slug": "p1", "title": "P1", "description": "d"}],
                    "subsections": [],
                },
                {
                    "slug": "sec-b",
                    "pages": [{"slug": "p2", "title": "P2", "description": "d"}],
                    "subsections": [],
                },
            ]
        }
        pages = _flatten_structure_pages(structure)
        assert len(pages) == 2
        assert pages[0]["section_path"] == "sec-a"
        assert pages[1]["section_path"] == "sec-b"

    def test_missing_optional_fields(self) -> None:
        structure = {
            "sections": [
                {
                    "slug": "sec",
                    "pages": [{"slug": "p", "title": "P"}],
                    "subsections": [],
                }
            ]
        }
        pages = _flatten_structure_pages(structure)
        assert pages[0]["description"] == ""
        assert pages[0]["source_file_hints"] == []
