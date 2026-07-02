"""
Health check routes for monitoring and uptime services.

These endpoints are designed for use with monitoring services like Pulsetic
to verify API availability and service health.
"""

import subprocess
import time
import logging
from fastapi import APIRouter, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# Separate router for .well-known verification endpoints (no prefix nesting)
well_known_router = APIRouter(prefix="/.well-known", tags=["well-known"])


@well_known_router.get("/openai-apps-challenge")
async def openai_apps_challenge():
    """OpenAI domain verification token."""
    return Response(
        content="ChDH9d9qwvXI5a0j04TwYJD7QJ4YNkrkYLE1uRUxW-U",
        media_type="text/plain",
    )


class HealthStatus(BaseModel):
    """Health check response model."""
    status: str
    timestamp: float


@router.get("/info")
async def server_info():
    """Returns backend metadata like the current git branch."""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        branch = ""
    return {"branch": branch}


@router.get("")
@router.get("/")
async def health_check() -> HealthStatus:
    """
    Basic health check endpoint.
    Returns a simple health status for uptime monitoring.
    """
    return HealthStatus(
        status="healthy",
        timestamp=time.time()
    )


@router.get("/db")
async def database_health(response: Response) -> dict:
    """
    Database connectivity health check.
    Performs an actual query to verify database is responsive.
    """
    try:
        from utils.database_pool import get_native_pool, get_pool_status

        start_time = time.time()
        await get_native_pool().fetchval("SELECT 1")
        query_time_ms = (time.time() - start_time) * 1000

        pool_status = get_pool_status()

        return {
            "status": "healthy",
            "query_time_ms": round(query_time_ms, 2),
            "pool": {
                "size": pool_status.get("size", 0),
                "max_size": pool_status.get("max_size", 0),
                "idle_size": pool_status.get("idle_size", 0),
            }
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        response.status_code = 503
        return {
            "status": "unhealthy",
            "error": str(e)
        }
