"""Ranking interface for candidate context items."""

from ..types import ToolContextItem


class RankingService:
    """Apply deterministic ordering over retrieved context candidates."""

    def rank(
        self, candidates: list[ToolContextItem], limit: int
    ) -> list[ToolContextItem]:
        """Return the top-N ranked candidates, preserving ranking order."""
        return candidates[:limit]
