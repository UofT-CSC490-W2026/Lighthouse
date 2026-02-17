from .code_graph import CodeGraphService
from .context import ContextService
from .conventions import ConventionService
from .dependencies import DependencyService
from .history import HistoryService
from .mental_model import MentalModelService
from .ranking import RankingService
from .semantic_search import SemanticSearchService

semantic_search_service = SemanticSearchService()
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
dependency_service = DependencyService()

__all__ = [
    "CodeGraphService",
    "ContextService",
    "ConventionService",
    "DependencyService",
    "HistoryService",
    "MentalModelService",
    "RankingService",
    "SemanticSearchService",
    "code_graph_service",
    "context_service",
    "convention_service",
    "dependency_service",
    "history_service",
    "mental_model_service",
    "ranking_service",
    "semantic_search_service",
]

