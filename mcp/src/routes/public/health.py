"""Health-check endpoint for service readiness/liveness probes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    """Return a minimal service health response."""
    return {"ok": True}
