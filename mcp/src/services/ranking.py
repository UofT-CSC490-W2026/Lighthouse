from ..types import ToolContextItem


class RankingService:
    """Placeholder service for ranking candidate context items."""

    def rank(
        self, candidates: list[ToolContextItem], limit: int
    ) -> list[ToolContextItem]:
        return candidates[:limit]
