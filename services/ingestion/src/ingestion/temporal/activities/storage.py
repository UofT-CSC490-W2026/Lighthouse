from __future__ import annotations

from temporalio import activity

from .helpers import get_settings
from ...utilities.services import ChunkService, FilePublishCleanupTarget
from .helpers import make_db, make_milvus
from .inputs import (
    CleanupInactiveChunksInput,
    CleanupStagingInput,
    DeleteChunksForFilesInput,
    DeleteChunksInput,
    FilePublishCleanup,
    PublishFullBranchInput,
    PublishStagedChunksInput,
    PublishStagedChunksOutput,
    StoreChunksInput,
)


@activity.defn
async def delete_existing_chunks(input: DeleteChunksInput) -> int:
    """Delete all chunks for a repo+branch from postgres and Milvus."""
    settings = get_settings()
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
    settings = get_settings()
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
    settings = get_settings()
    db = make_db(settings)
    milvus = make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        return svc.move_to_final(input.batch_id)
    finally:
        db.close()
        milvus.close()


@activity.defn
async def publish_staged_chunks(
    input: PublishStagedChunksInput,
) -> PublishStagedChunksOutput:
    """Publish staged chunks and switch active file versions."""
    settings = get_settings()
    db = make_db(settings)
    milvus = make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        cleanup_targets = svc.publish_incremental_batch(
            batch_id=input.batch_id,
            repository_id=input.repository_id,
            branch=input.branch,
            changed_files=input.changed_files,
        )
        return PublishStagedChunksOutput(
            cleanup_targets=[
                FilePublishCleanup(
                    file_path=target.file_path,
                    previous_publish_id=target.previous_publish_id,
                )
                for target in cleanup_targets
            ]
        )
    finally:
        db.close()
        milvus.close()


@activity.defn
async def publish_full_branch(
    input: PublishFullBranchInput,
) -> PublishStagedChunksOutput:
    """Publish all staged chunks for a full re-index and switch active file versions."""
    settings = get_settings()
    db = make_db(settings)
    milvus = make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        cleanup_targets = svc.publish_full_batch(
            batch_id=input.batch_id,
            repository_id=input.repository_id,
            branch=input.branch,
        )
        return PublishStagedChunksOutput(
            cleanup_targets=[
                FilePublishCleanup(
                    file_path=target.file_path,
                    previous_publish_id=target.previous_publish_id,
                )
                for target in cleanup_targets
            ]
        )
    finally:
        db.close()
        milvus.close()


@activity.defn
async def cleanup_inactive_chunks(input: CleanupInactiveChunksInput) -> int:
    """Delete stale chunks for files after active publish has switched."""
    settings = get_settings()
    db = make_db(settings)
    milvus = make_milvus(settings)
    try:
        svc = ChunkService(db, milvus)
        return svc.delete_by_publish_targets(
            repository_id=input.repository_id,
            branch=input.branch,
            cleanup_targets=[
                FilePublishCleanupTarget(
                    file_path=target.file_path,
                    previous_publish_id=target.previous_publish_id,
                )
                for target in input.cleanup_targets
            ],
        )
    finally:
        db.close()
        milvus.close()


@activity.defn
async def cleanup_staging(input: CleanupStagingInput) -> str:
    """Clean up staging rows on failure."""
    settings = get_settings()
    db = make_db(settings)
    try:
        svc = ChunkService(db)
        svc.cleanup_staging(input.batch_id)
        return "cleaned"
    finally:
        db.close()
