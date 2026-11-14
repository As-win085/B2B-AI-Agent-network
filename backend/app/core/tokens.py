"""JWT access-token issuance and validation.

Only short-lived access tokens are JWTs. Refresh tokens are opaque random
strings stored as hashes in ``refresh_sessions`` (see ``app.core.security``).

An access token is bound to one server-side session (``sid``). Revoking the
session therefore invalidates the token immediately, even before it expires.
The active organization is **not** trusted from the token: it is resolved from
the session row and re-validated against ``organization_members`` on every
request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt

from app.core.config import settings

_TOKEN_TYPE = "access"
_ISSUER = "asama.ai"
_AUDIENCE = "asama.ai/api"
_REQUIRED_CLAIMS = ("exp", "iat", "sub", "sid", "jti", "type")


class TokenValidationError(Exception):
    """Raised when an access token cannot be trusted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    token_id: str
    issued_at: datetime
    expires_at: datetime


def create_access_token(*, user_id: UUID, session_id: UUID) -> tuple[str, datetime]:
    """Return a signed access token and its expiry time."""

    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "jti": uuid4().hex,
        "type": _TOKEN_TYPE,
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> AccessTokenClaims:
    """Validate signature, expiry, issuer, audience and required claims."""

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            options={"require": list(_REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenValidationError("token_expired", "Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenValidationError("invalid_token", "Access token is invalid.") from exc

    if payload.get("type") != _TOKEN_TYPE:
        raise TokenValidationError("invalid_token", "Access token is invalid.")

    try:
        return AccessTokenClaims(
            user_id=UUID(str(payload["sub"])),
            session_id=UUID(str(payload["sid"])),
            token_id=str(payload["jti"]),
            issued_at=datetime.fromtimestamp(int(payload["iat"]), tz=UTC),
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenValidationError("invalid_token", "Access token is invalid.") from exc
