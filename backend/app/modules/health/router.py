"""Health and readiness routes.

``/health`` is liveness only: it proves the process is running.
``/health/ready`` checks PostgreSQL, Redis and RabbitMQ.

Infrastructure probes mounted at the root keep a plain response body. The
versioned ``/api/v1/health`` endpoints use the canonical success envelope.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.responses import ApiResponse, success
from app.modules.health.schemas import HealthResponse
from app.modules.health.service import check_dependencies

# Root-level probe router: plain body, excluded from the OpenAPI schema.
router = APIRouter(tags=["health"])
# Versioned router: canonical envelope, documented in OpenAPI.
versioned_router = APIRouter(tags=["health"])


def _base_payload() -> dict:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "timestamp": datetime.now(UTC),
    }


def _liveness() -> HealthResponse:
    return HealthResponse(status="ok", **_base_payload())


def _readiness() -> tuple[HealthResponse, int]:
    components = check_dependencies()
    healthy = all(component.ok for component in components)
    payload = HealthResponse(
        status="ok" if healthy else "degraded",
        components=components,
        **_base_payload(),
    )
    return payload, 200 if healthy else 503


@router.get("/health", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return _liveness()


@router.get("/health/ready", response_model=HealthResponse)
def readiness() -> JSONResponse:
    payload, status_code = _readiness()
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


@versioned_router.get(
    "/health",
    response_model=ApiResponse[HealthResponse],
    response_model_exclude_none=True,
)
def versioned_liveness() -> dict:
    return success(_liveness())


@versioned_router.get(
    "/health/ready",
    response_model=ApiResponse[HealthResponse],
    response_model_exclude_none=True,
)
def versioned_readiness() -> JSONResponse:
    payload, status_code = _readiness()
    return JSONResponse(
        status_code=status_code,
        content={"data": payload.model_dump(mode="json")},
    )
