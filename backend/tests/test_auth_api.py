"""ASAMA-103: registration, login, refresh and logout endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from app.core.config import settings

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

PASSWORD = "correct horse battery staple"


def register_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "email": "owner@example.test",
        "password": PASSWORD,
        "full_name": "Ada Owner",
        "organization_name": "Acme",
    }
    payload.update(overrides)
    return payload


def register(client: TestClient, **overrides: Any):
    return client.post(REGISTER, json=register_payload(**overrides))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_creates_user_organization_and_owner_membership(api_client: TestClient) -> None:
    response = register(api_client)

    assert response.status_code == 201
    body = response.json()
    data = body["data"]
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["expires_in"] > 0
    assert data["user"]["email"] == "owner@example.test"
    assert data["user"]["is_active"] is True
    assert data["organization"]["name"] == "Acme"
    assert data["organization"]["slug"] == "acme"
    assert data["organization"]["role"] == "owner"
    assert [org["role"] for org in data["organizations"]] == ["owner"]
    assert "password" not in response.text
    assert PASSWORD not in response.text


def test_register_normalizes_email(api_client: TestClient) -> None:
    response = register(api_client, email="  Owner@Example.TEST ")

    assert response.status_code == 201
    assert response.json()["data"]["user"]["email"] == "owner@example.test"


def test_register_rejects_case_insensitive_duplicate_email(api_client: TestClient) -> None:
    assert register(api_client, email="owner@example.test").status_code == 201

    response = register(api_client, email="OWNER@Example.Test", organization_name="Other")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "email_already_registered"
    assert error["details"] == [{"field": "email"}]
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_register_rejects_duplicate_organization_slug(api_client: TestClient) -> None:
    assert register(api_client, organization_slug="acme").status_code == 201

    response = register(
        api_client,
        email="second@example.test",
        organization_name="Acme Again",
        organization_slug="acme",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "organization_slug_taken"


def test_register_generates_unique_slug_for_same_name(api_client: TestClient) -> None:
    first = register(api_client)
    second = register(api_client, email="second@example.test")

    assert first.status_code == 201
    assert second.status_code == 201
    assert (
        first.json()["data"]["organization"]["slug"]
        != (second.json()["data"]["organization"]["slug"])
    )


def test_register_rejects_weak_password(api_client: TestClient) -> None:
    response = register(api_client, password="short")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "body.password"


def test_register_rejects_invalid_email(api_client: TestClient) -> None:
    response = register(api_client, email="not-an-email")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.email"


def test_login_succeeds_with_correct_credentials(api_client: TestClient) -> None:
    assert register(api_client).status_code == 201

    response = api_client.post(LOGIN, json={"email": "owner@example.test", "password": PASSWORD})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["organization"]["slug"] == "acme"


def test_login_is_case_insensitive(api_client: TestClient) -> None:
    assert register(api_client, email="owner@example.test").status_code == 201

    response = api_client.post(
        LOGIN,
        json={"email": "OWNER@Example.Test", "password": PASSWORD},
    )

    assert response.status_code == 200


def test_login_rejects_wrong_password_without_leaking_details(api_client: TestClient) -> None:
    assert register(api_client).status_code == 201

    response = api_client.post(
        LOGIN, json={"email": "owner@example.test", "password": "wrong pass"}
    )

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "invalid_credentials"
    assert error["message"] == "Invalid email or password."
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_login_unknown_email_matches_wrong_password_response(api_client: TestClient) -> None:
    assert register(api_client).status_code == 201

    known = api_client.post(
        LOGIN, json={"email": "owner@example.test", "password": "definitely wrong"}
    )
    unknown = api_client.post(
        LOGIN, json={"email": "nobody@example.test", "password": "definitely wrong"}
    )

    assert unknown.status_code == known.status_code == 401
    assert unknown.json()["error"]["code"] == known.json()["error"]["code"]
    assert unknown.json()["error"]["message"] == known.json()["error"]["message"]


def test_me_requires_authentication(api_client: TestClient) -> None:
    response = api_client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_returns_user_and_organization(api_client: TestClient) -> None:
    token = register(api_client).json()["data"]["access_token"]

    response = api_client.get(ME, headers=bearer(token))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["email"] == "owner@example.test"
    assert data["organization"]["role"] == "owner"


def test_me_rejects_invalid_token(api_client: TestClient) -> None:
    response = api_client.get(ME, headers=bearer("not-a-jwt"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_me_rejects_expired_token(api_client: TestClient) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "jti": uuid4().hex,
            "type": "access",
            "iss": "asama.ai",
            "aud": "asama.ai/api",
            "iat": int((now - timedelta(minutes=10)).timestamp()),
            "exp": int((now - timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = api_client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_refresh_rotates_tokens_and_revokes_previous_session(api_client: TestClient) -> None:
    session = register(api_client).json()["data"]

    refreshed = api_client.post(REFRESH, json={"refresh_token": session["refresh_token"]})

    assert refreshed.status_code == 200
    rotated = refreshed.json()["data"]
    assert rotated["refresh_token"] != session["refresh_token"]
    assert rotated["access_token"] != session["access_token"]

    # The old refresh token is now a replay: the whole family is revoked.
    replay = api_client.post(REFRESH, json={"refresh_token": session["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_token_reused"

    # Rotating invalidated the previous access token too.
    old_access = api_client.get(ME, headers=bearer(session["access_token"]))
    assert old_access.status_code == 401
    assert old_access.json()["error"]["code"] == "session_revoked"

    # Replaying the family also killed the freshly rotated token.
    newest = api_client.get(ME, headers=bearer(rotated["access_token"]))
    assert newest.status_code == 401


def test_refresh_rejects_unknown_token(api_client: TestClient) -> None:
    response = api_client.post(REFRESH, json={"refresh_token": "unknown-refresh-token-value"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


def test_logout_revokes_session_and_is_idempotent(api_client: TestClient) -> None:
    session = register(api_client).json()["data"]

    logged_out = api_client.post(LOGOUT, json={"refresh_token": session["refresh_token"]})
    assert logged_out.status_code == 200
    assert logged_out.json()["data"] == {"logged_out": True}

    # Idempotent for an unknown token.
    unknown = api_client.post(LOGOUT, json={"refresh_token": "unknown-refresh-token-value"})
    assert unknown.status_code == 200
    assert unknown.json()["data"] == {"logged_out": True}

    # The access token bound to the revoked session stops working.
    me = api_client.get(ME, headers=bearer(session["access_token"]))
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "session_revoked"

    refresh = api_client.post(REFRESH, json={"refresh_token": session["refresh_token"]})
    assert refresh.status_code == 401
