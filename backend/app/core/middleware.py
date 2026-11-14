"""ASGI middleware for request correlation.

Every HTTP request receives a request ID: the caller's ``X-Request-ID`` when it
is safe, otherwise a generated UUID4. The value is stored in the request scope
and a context variable, and echoed on the response.
"""

from __future__ import annotations

from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import (
    REQUEST_ID_HEADER,
    normalize_request_id,
    reset_request_id,
    set_request_id,
)


class RequestContextMiddleware:
    """Attach a request ID to the scope, context and response headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = normalize_request_id(headers.get(REQUEST_ID_HEADER)) or str(uuid4())

        token = set_request_id(request_id)
        # Also store on scope so exception handlers can read it after the
        # context variable has been reset by the ``finally`` block below.
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            reset_request_id(token)
