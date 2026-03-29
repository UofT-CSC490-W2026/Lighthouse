from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from temporalio import activity

from ...embedding import EmbeddingStrategy, get_embedding_provider
from ...llm import LLMStrategy, get_llm_provider
from ...utilities.services import WikiService
from ...wiki.prompts import build_page_prompt, build_structure_prompt
from .helpers import get_settings, make_db, make_milvus, make_wiki_milvus

logger = logging.getLogger(__name__)

WIKI_EMBED_BATCH_SIZE = 512

# Limits for the structure generation prompt
MAX_FILE_PATHS = 500
MAX_SAMPLE_CHUNKS = 20


# --- Input / Output dataclasses ---


@dataclass
class GenerateWikiInput:
    """Workflow-level input."""

    repository_id: str
    github_repo_id: int
    full_name: str
    branch: str
    llm_strategy: str = "openai"
    embedding_strategy: str = "openai"


@dataclass
class GenerateWikiStructureInput:
    repository_id: str
    full_name: str
    branch: str
    llm_strategy: str = "openai"


@dataclass
class GenerateWikiStructureOutput:
    batch_id: str
    wiki_generation_id: str
    page_count: int
    structure_json: str


@dataclass
class GenerateWikiPageInput:
    batch_id: str
    wiki_generation_id: str
    repository_id: str
    branch: str
    page_slug: str
    page_title: str
    page_description: str
    section_path: str
    source_file_hints: list[str] = field(default_factory=list)
    llm_strategy: str = "openai"
    embedding_strategy: str = "openai"


@dataclass
class EmbedWikiPagesInput:
    batch_id: str
    offset: int
    limit: int
    embedding_strategy: str = "openai"


@dataclass
class StoreWikiPagesInput:
    batch_id: str
    wiki_generation_id: str


@dataclass
class UpdateWikiStatusInput:
    wiki_generation_id: str
    status: str
    page_count: int = 0


@dataclass
class CleanupStagingWikiInput:
    batch_id: str


# --- Activities ---


@activity.defn
async def generate_wiki_structure(input: GenerateWikiStructureInput) -> GenerateWikiStructureOutput:
    """Analyze repo chunks and produce a wiki outline via LLM."""
    from db import Chunk

    settings = get_settings()
    db = make_db(settings)
    llm = get_llm_provider(
        LLMStrategy(input.llm_strategy),
        api_key=settings.openai_api_key,
    )

    try:
        svc = WikiService(db)

        with db.connection_context():
            # Gather file paths from existing chunks
            file_paths = [
                row.file_path
                for row in (
                    Chunk.select(Chunk.file_path)
                    .where(
                        (Chunk.repository == input.repository_id)
                        & (Chunk.branch == input.branch)
                    )
                    .distinct()
                    .limit(MAX_FILE_PATHS)
                )
            ]

            # Sample some chunks for context
            sample_chunks = [
                f"### {row.file_path} (lines {row.start_line}-{row.end_line})\n```\n{row.content}\n```"
                for row in (
                    Chunk.select(Chunk.file_path, Chunk.start_line, Chunk.end_line, Chunk.content)
                    .where(
                        (Chunk.repository == input.repository_id)
                        & (Chunk.branch == input.branch)
                    )
                    .order_by(Chunk.file_path, Chunk.start_line)
                    .limit(MAX_SAMPLE_CHUNKS)
                )
            ]

        if not file_paths:
            raise RuntimeError(
                f"No indexed chunks found for {input.full_name}/{input.branch}. "
                "Index the repository before generating a wiki."
            )

        # Call LLM to generate wiki structure
        messages = build_structure_prompt(file_paths, sample_chunks, input.full_name)
        structure_dict = llm.complete_json(messages)
        structure_json = json.dumps(structure_dict)

        # Flatten pages from the structure
        pages = _flatten_structure_pages(structure_dict)
        if not pages:
            raise RuntimeError("LLM produced a wiki structure with no pages.")

        batch_id = str(uuid.uuid4())

        # Create WikiGeneration record
        generation = svc.create_generation(
            repository_id=input.repository_id,
            branch=input.branch,
            wiki_title=structure_dict.get("title", input.full_name),
            wiki_description=structure_dict.get("description", ""),
            structure_json=structure_json,
            page_count=len(pages),
        )

        # Write staging rows (empty content, to be filled per-page)
        staging_pages = [
            {
                "id": str(uuid.uuid4()),
                "repository_id": input.repository_id,
                "branch": input.branch,
                "slug": p["slug"],
                "title": p["title"],
                "content": "",
                "section_path": p["section_path"],
                "source_files": json.dumps(p.get("source_file_hints", [])),
            }
            for p in pages
        ]
        svc.write_staging(batch_id, staging_pages)

        return GenerateWikiStructureOutput(
            batch_id=batch_id,
            wiki_generation_id=generation.id,
            page_count=len(pages),
            structure_json=structure_json,
        )
    finally:
        db.close()


@activity.defn
async def generate_wiki_page(input: GenerateWikiPageInput) -> str:
    """Generate content for a single wiki page via RAG + LLM."""
    from db import Chunk

    settings = get_settings()
    db = make_db(settings)
    milvus = make_milvus(settings)
    embedder = get_embedding_provider(
        EmbeddingStrategy(input.embedding_strategy),
        api_key=settings.openai_api_key,
    )
    llm = get_llm_provider(
        LLMStrategy(input.llm_strategy),
        api_key=settings.openai_api_key,
    )

    try:
        svc = WikiService(db)

        # RAG: embed the page description and search existing code chunks
        query_text = f"{input.page_title}: {input.page_description}"
        query_embedding = embedder.embed_single(query_text)

        # Vector search in existing code chunks
        results = milvus.search(
            query_embedding=query_embedding,
            top_k=15,
            filters={
                "repository_id": input.repository_id,
                "branch": input.branch,
            },
        )
        chunk_ids = [r.chunk_id for r in results]

        # Fetch full chunk content from postgres
        context_chunks = []
        if chunk_ids:
            with db.connection_context():
                chunks = list(
                    Chunk.select()
                    .where(Chunk.id.in_(chunk_ids))
                )
                context_chunks = [
                    f"### {c.file_path} (lines {c.start_line}-{c.end_line})\n```{c.language or ''}\n{c.content}\n```"
                    for c in chunks
                ]

        # Generate page content via LLM
        messages = build_page_prompt(input.page_title, input.page_description, context_chunks)
        content = llm.complete(messages)

        # Update staging row with generated content
        svc.update_staging_content_by_slug(input.batch_id, input.page_slug, content)

        return f"generated:{input.page_slug}"
    finally:
        db.close()
        milvus.close()


@activity.defn
async def embed_wiki_pages(input: EmbedWikiPagesInput) -> str:
    """Embed a batch of staging wiki pages and write vectors back."""
    settings = get_settings()
    db = make_db(settings)
    embedder = get_embedding_provider(
        EmbeddingStrategy(input.embedding_strategy),
        api_key=settings.openai_api_key,
    )
    try:
        svc = WikiService(db)
        pages = svc.read_staging_batch(input.batch_id, input.offset, input.limit)
        if not pages:
            return "no_pages"
        texts = [p.content for p in pages]
        embeddings = embedder.embed_batch(texts)
        svc.write_staging_embeddings(input.batch_id, input.offset, embeddings)
        return f"embedded_{len(pages)}"
    finally:
        db.close()


@activity.defn
async def store_wiki_pages(input: StoreWikiPagesInput) -> int:
    """Move staging wiki pages to final table and Milvus."""
    settings = get_settings()
    db = make_db(settings)
    milvus = make_wiki_milvus(settings)
    try:
        svc = WikiService(db, milvus)
        return svc.move_to_final(input.batch_id, input.wiki_generation_id)
    finally:
        db.close()
        milvus.close()


@activity.defn
async def update_wiki_status(input: UpdateWikiStatusInput) -> str:
    """Update the status of a WikiGeneration record."""
    settings = get_settings()
    db = make_db(settings)
    try:
        svc = WikiService(db)
        svc.update_status(input.wiki_generation_id, input.status, input.page_count)
        return input.status
    finally:
        db.close()


@activity.defn
async def cleanup_staging_wiki(input: CleanupStagingWikiInput) -> str:
    """Clean up staging wiki rows on failure."""
    settings = get_settings()
    db = make_db(settings)
    try:
        svc = WikiService(db)
        svc.cleanup_staging(input.batch_id)
        return "cleaned"
    finally:
        db.close()


# --- Helpers ---


def _flatten_structure_pages(
    structure: dict, section_path: str = ""
) -> list[dict]:
    """Recursively flatten a WikiStructure dict into a flat list of page defs."""
    pages = []
    # Top-level uses "sections", nested levels use "subsections"
    sections = structure.get("sections", []) or structure.get("subsections", [])
    for section in sections:
        current_path = f"{section_path}/{section['slug']}" if section_path else section["slug"]
        for page in section.get("pages", []):
            pages.append({
                "slug": page["slug"],
                "title": page["title"],
                "description": page.get("description", ""),
                "section_path": current_path,
                "source_file_hints": page.get("source_file_hints", []),
            })
        # Recurse into subsections
        pages.extend(_flatten_structure_pages(section, current_path))
    return pages
