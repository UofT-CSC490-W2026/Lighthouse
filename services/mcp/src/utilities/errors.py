class RequestError(Exception):
    """Represent a client-facing request error with an explicit status code."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        """Create a request error with a serialized message and HTTP status."""
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
