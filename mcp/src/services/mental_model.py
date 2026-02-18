"""Mental-model signal retrieval interface used during context assembly."""

class MentalModelService:
    """Fetch repository-level heuristics and module-specific behavior signals."""

    async def get_module_signals(self, file_path: str) -> list[str]:
        """Return ranked signals for a file path to aid context interpretation."""
        _ = file_path
        return []
