from __future__ import annotations

from temporalio import activity

from ...utilities.config import IngestionSettings
from ...utilities.services import ChunkService
from .helpers import make_db, make_milvus
from .inputs import (
    CleanupStagingInput,
    DeleteChunksForFilesInput,
    DeleteChunksInput,
    StoreChunksInput,
)


@activity.defn
async def delete_existing_chunks(input: DeleteChunksInput) -> int:
    """Delete all chunks for a repo+branch from postgres and Milvus."""
    settings = IngestionSettings()
    db = make_db(settings)
    milvus = make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        return svc.delete_by_branch(input.repository_id, input.branch)
    finally:
        db.close()
        milvus.close()


@activity.defn
async def delete_chunks_for_files(input: DeleteChunksForFilesInput) -> int:
    """Delete chunks for specific files from postgres and Milvus."""
    settings = IngestionSettings()
    db = make_db(settings)
    milvus = make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        return svc.delete_by_files(input.repository_id, input.branch, input.file_paths)
    finally:
        db.close()
        milvus.close()


@activity.defn
async def store_chunks(input: StoreChunksInput) -> int:
    """Move staging chunks to final tables and Milvus."""
    settings = IngestionSettings()
    db = make_db(settings)
    milvus = make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        return svc.move_to_final(input.batch_id)
    finally:
        db.close()
        milvus.close()


@activity.defn
async def cleanup_staging(input: CleanupStagingInput) -> str:
    """Clean up staging rows on failure."""
    settings = IngestionSettings()
    db = make_db(settings)
    try:
        svc = ChunkService(db)
        svc.cleanup_staging(input.batch_id)
        return "cleaned"
    finally:
        db.close()
