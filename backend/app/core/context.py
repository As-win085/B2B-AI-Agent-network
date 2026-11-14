"""Request-scoped context values.

The request ID is stored in a :mod:`contextvars` variable so log records and
background calls made during the same request can be correlated without
threading the value through every function signature.
"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token

REQUEST_ID_HEADER = "X-Request-ID"

# Accept caller-supplied IDs only when they are safe to log and echo.
# This prevents header/log injection through the correlation ID.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request ID, if one is active."""

    return _request_id.get()


def set_request_id(value: str) -> Token[str | None]:
    """Bind a request ID to the current context."""

    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request ID context."""

    _request_id.reset(token)


def normalize_request_id(value: str | None) -> str | None:
    """Return a safe caller-supplied request ID, or ``None`` when invalid."""

    if not value:
        return None

    candidate = value.strip()
    if not _REQUEST_ID_PATTERN.fullmatch(candidate):
        return None

    return candidate
