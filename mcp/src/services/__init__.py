"""Service registry and singleton wiring for the MCP application.

This module provides import-stable service instances used by route handlers.
"""

from ..clients import TemporalClientWrapper
from .code_graph import CodeGraphService
from .context import ContextService
from .conventions import ConventionService
from .dependencies import DependencyService
from .history import HistoryService
from .index_control import IndexControlService
from .index_repository import IndexRepository
from .mental_model import MentalModelService
from .ranking import RankingService
from .retrieval_backend import RetrievalBackendService
from .semantic_search import SemanticSearchService

retrieval_backend_service = RetrievalBackendService()
semantic_search_service = SemanticSearchService(
    retrieval_backend=retrieval_backend_service
)
ranking_service = RankingService()
mental_model_service = MentalModelService()

context_service = ContextService(
    semantic_search_service=semantic_search_service,
    ranking_service=ranking_service,
    mental_model_service=mental_model_service,
)
code_graph_service = CodeGraphService()
history_service = HistoryService()
convention_service = ConventionService()
dependency_service = DependencyService(
    retrieval_backend=retrieval_backend_service,
)
temporal_client = TemporalClientWrapper()
index_repository = IndexRepository()
index_control_service = IndexControlService(
    temporal_client=temporal_client,
    repository=index_repository,
)

__all__ = [
    "CodeGraphService",
    "ContextService",
    "ConventionService",
    "DependencyService",
    "HistoryService",
    "IndexControlService",
    "IndexRepository",
    "MentalModelService",
    "RankingService",
    "RetrievalBackendService",
    "SemanticSearchService",
    "code_graph_service",
    "context_service",
    "convention_service",
    "dependency_service",
    "history_service",
    "index_control_service",
    "index_repository",
    "mental_model_service",
    "ranking_service",
    "retrieval_backend_service",
    "semantic_search_service",
    "temporal_client",
]
