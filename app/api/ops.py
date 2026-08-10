"""Operational endpoints (unversioned): health and Prometheus metrics."""

from typing import Any

import structlog
from fastapi import APIRouter, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

router = APIRouter(tags=["ops"])

logger = structlog.get_logger(__name__)


@router.get("/health")
async def health(request: Request, response: Response) -> dict[str, Any]:
    """Liveness and readiness probe.

    Checks connectivity to PostgreSQL and Redis. Returns HTTP 200 when all
    components are healthy, HTTP 503 with per-component status otherwise.
    """
    checks: dict[str, str] = {}

    try:
        session_factory = request.app.state.session_factory
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.warning("health_check_failed", component="database", exc_info=True)
        checks["database"] = "error"

    try:
        redis = request.app.state.redis
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        logger.warning("health_check_failed", component="redis", exc_info=True)
        checks["redis"] = "error"

    healthy = all(value == "ok" for value in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if healthy else "degraded", "checks": checks}


@router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
