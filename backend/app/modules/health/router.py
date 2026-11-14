"""Health and readiness routes.

``/health`` is liveness only: it proves the process is running.
``/health/ready`` checks PostgreSQL, Redis and RabbitMQ.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.modules.health.schemas import HealthResponse
from app.modules.health.service import check_dependencies

router = APIRouter(tags=["health"])


def _base_payload() -> dict:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "timestamp": datetime.now(UTC),
    }


@router.get("/health", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse(status="ok", **_base_payload())


@router.get("/health/ready", response_model=HealthResponse)
def readiness() -> JSONResponse:
    components = check_dependencies()
    healthy = all(component.ok for component in components)
    payload = HealthResponse(
        status="ok" if healthy else "degraded",
        components=components,
        **_base_payload(),
    )
    return JSONResponse(
        status_code=200 if healthy else 503,
        content=payload.model_dump(mode="json"),
    )
