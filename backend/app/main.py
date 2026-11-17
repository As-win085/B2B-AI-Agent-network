"""Application entry point.

Run locally from the ``backend`` directory:

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.responses import error_response
from app.modules.agents.router import router as agents_router
from app.modules.auth.router import router as auth_router
from app.modules.comments.router import router as comments_router
from app.modules.health.router import router as health_router
from app.modules.health.router import versioned_router as versioned_health_router
from app.modules.organizations.router import router as organizations_router
from app.modules.posts.router import router as posts_router

logger = logging.getLogger(__name__)

_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def create_app() -> FastAPI:
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="B2B event-driven network for autonomous AI agents.",
    )

    # Added first so the request-context middleware wraps CORS (and therefore
    # also covers preflight responses added below).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    # Root-level health endpoints (infrastructure probes, plain body).
    app.include_router(health_router, include_in_schema=False)
    # Versioned health endpoints (enveloped API contract).
    app.include_router(versioned_health_router, prefix=settings.api_v1_prefix)
    # Human authentication and organization-scoped authorization.
    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(organizations_router, prefix=settings.api_v1_prefix)
    app.include_router(agents_router, prefix=settings.api_v1_prefix)
    app.include_router(posts_router, prefix=settings.api_v1_prefix)
    app.include_router(comments_router, prefix=settings.api_v1_prefix)

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "environment": settings.app_env,
            "docs": "/docs",
            "health": "/health",
        }

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            exc.status_code,
            exc.code,
            exc.message,
            details=exc.details,
            request_id=_request_id(request),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "message": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors()
        ]
        return error_response(
            422,
            "validation_error",
            "Request validation failed.",
            details=details,
            request_id=_request_id(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(
            exc.status_code,
            code,
            message,
            request_id=_request_id(request),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception",
            extra={"request_id": _request_id(request)},
        )
        return error_response(
            500,
            "internal_error",
            "An unexpected error occurred.",
            request_id=_request_id(request),
        )

    return app


app = create_app()
