"""Pipeline-facing Milvus connector for runtime retrieval persistence."""

from __future__ import annotations

from runtime_retrieval import MilvusRuntimeRetrievalStore


class MilvusConnector(MilvusRuntimeRetrievalStore):
    """Pipeline wrapper over shared runtime retrieval store semantics."""

    pass
