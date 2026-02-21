"""Re-export canonical indexing enums for pipeline-local imports."""

from .contracts.indexing import IndexStage, IndexStatus

__all__ = ["IndexStatus", "IndexStage"]
