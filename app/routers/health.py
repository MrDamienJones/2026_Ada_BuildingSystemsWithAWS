"""Health check router.

Provides a simple GET /health endpoint that returns HTTP 200 with {"status": "ok"}.
Used by load balancers, container orchestrators, and monitoring tools to verify
the application is running.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """Return health status of the application."""
    return {"status": "ok"}
