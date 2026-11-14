"""ASAMA-103: JWT access-token issuance and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import settings
from app.core.tokens import (
    AccessTokenClaims,
    TokenValidationError,
    create_access_token,
    decode_access_token,
)


def test_access_token_round_trip() -> None:
    user_id = uuid4()
    session_id = uuid4()

    token, expires_at = create_access_token(user_id=user_id, session_id=session_id)
    claims = decode_access_token(token)

    assert isinstance(claims, AccessTokenClaims)
    assert claims.user_id == user_id
    assert claims.session_id == session_id
    # JWT timestamps have second precision.
    assert int(claims.expires_at.timestamp()) == int(expires_at.timestamp())
    assert claims.token_id


def _encode(**overrides: object) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "jti": uuid4().hex,
        "type": "access",
        "iss": "asama.ai",
        "aud": "asama.ai/api",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    payload.update(overrides)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_expired_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(minutes=1)
    token = _encode(exp=int(past.timestamp()))

    with pytest.raises(TokenValidationError) as excinfo:
        decode_access_token(token)
    assert excinfo.value.code == "token_expired"


def test_invalid_signature_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "jti": uuid4().hex,
            "type": "access",
            "iss": "asama.ai",
            "aud": "asama.ai/api",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        "a-completely-different-signing-key",
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenValidationError) as excinfo:
        decode_access_token(token)
    assert excinfo.value.code == "invalid_token"


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "refresh"},
        {"iss": "someone.else"},
        {"aud": "someone.else/api"},
        {"sub": "not-a-uuid"},
        {"sid": "not-a-uuid"},
    ],
)
def test_malformed_claims_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(TokenValidationError) as excinfo:
        decode_access_token(_encode(**overrides))
    assert excinfo.value.code == "invalid_token"


def test_missing_required_claim_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "type": "access",
            "iss": "asama.ai",
            "aud": "asama.ai/api",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenValidationError):
        decode_access_token(token)


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(TokenValidationError):
        decode_access_token("not.a.jwt")
