"""Canonical API response envelope.

All versioned API responses use one of two shapes:

Success::

    {"data": ...}
    {"data": [...], "meta": {"page": 1, "page_size": 20, "total": 42}}

Error::

    {"error": {"code": "...", "message": "...", "details": [...], "request_id": "..."}}

Infrastructure probes (``/health`` and ``/health/ready``) intentionally keep
their plain response contract.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.context import REQUEST_ID_HEADER, get_request_id


class ApiResponse[T](BaseModel):
    """Success envelope used in OpenAPI schemas."""

    data: T
    meta: dict[str, Any] | None = None


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str
    type: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def success(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a success envelope payload."""

    payload: dict[str, Any] = {"data": data}
    if meta is not None:
        payload["meta"] = meta
    return payload


def error_payload(
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build an error envelope payload."""

    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id or get_request_id(),
    }
    if details:
        error["details"] = details
    return {"error": error}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    """Build a JSON error response with the canonical envelope."""

    resolved_id = request_id or get_request_id()
    headers = {REQUEST_ID_HEADER: resolved_id} if resolved_id else None
    return JSONResponse(
        status_code=status_code,
        content=error_payload(
            code,
            message,
            details=details,
            request_id=resolved_id,
        ),
        headers=headers,
    )
