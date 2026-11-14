"""ASAMA-103: authentication against live PostgreSQL.

Skipped unless ``RUN_INTEGRATION_TESTS=1``. Each test creates uniquely named
accounts and removes them again, so the shared database stays clean.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import engine
from app.main import app

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery staple"


def _suffix() -> str:
    return uuid.uuid4().hex[:12]


def _cleanup(suffix: str) -> None:
    pattern = f"%{suffix}%"
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM refresh_sessions WHERE user_id IN "
                "(SELECT id FROM users WHERE email LIKE :pattern)"
            ),
            {"pattern": pattern},
        )
        connection.execute(
            text(
                "DELETE FROM organization_members WHERE user_id IN "
                "(SELECT id FROM users WHERE email LIKE :pattern)"
            ),
            {"pattern": pattern},
        )
        connection.execute(
            text("DELETE FROM organizations WHERE slug LIKE :pattern"),
            {"pattern": pattern},
        )
        connection.execute(
            text("DELETE FROM users WHERE email LIKE :pattern"), {"pattern": pattern}
        )


def _register(client: TestClient, email: str, organization_name: str):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "organization_name": organization_name,
        },
    )


def test_registration_login_and_refresh_against_postgres() -> None:
    suffix = _suffix()
    email = f"owner-{suffix}@example.test"
    client = TestClient(app)

    try:
        registered = _register(client, email, f"Acme {suffix}")
        assert registered.status_code == 201, registered.text
        session = registered.json()["data"]
        assert session["organization"]["role"] == "owner"
        assert session["organization"]["slug"] == f"acme-{suffix}"

        with engine.connect() as connection:
            stored_hash = connection.execute(
                text("SELECT password_hash FROM users WHERE email = :email"),
                {"email": email},
            ).scalar_one()
            assert stored_hash.startswith("scrypt$")
            assert PASSWORD not in stored_hash

            token_row = connection.execute(
                text(
                    "SELECT token_hash FROM refresh_sessions WHERE user_id = "
                    "(SELECT id FROM users WHERE email = :email)"
                ),
                {"email": email},
            ).scalar_one()
            assert token_row == hashlib.sha256(session["refresh_token"].encode()).hexdigest()
            assert token_row != session["refresh_token"]

        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["data"]["user"]["email"] == email

        refreshed = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]}
        )
        assert refreshed.status_code == 200, refreshed.text
        rotated = refreshed.json()["data"]
        assert rotated["refresh_token"] != session["refresh_token"]

        replay = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]}
        )
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "refresh_token_reused"

        logged_out = client.post(
            "/api/v1/auth/logout", json={"refresh_token": rotated["refresh_token"]}
        )
        assert logged_out.status_code == 200

        after_logout = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {rotated['access_token']}"},
        )
        assert after_logout.status_code == 401
    finally:
        _cleanup(suffix)


def test_duplicate_email_is_case_insensitive_in_postgres() -> None:
    suffix = _suffix()
    email = f"owner-{suffix}@example.test"
    client = TestClient(app)

    try:
        assert _register(client, email, f"Acme {suffix}").status_code == 201

        duplicate = _register(client, email.upper(), f"Other {suffix}")
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "email_already_registered"
    finally:
        _cleanup(suffix)


def test_cross_tenant_access_is_blocked_in_postgres() -> None:
    suffix = _suffix()
    owner_email = f"owner-{suffix}@example.test"
    outsider_email = f"outsider-{suffix}@example.test"
    client = TestClient(app)

    try:
        owner = _register(client, owner_email, f"Acme {suffix}").json()["data"]
        outsider = _register(client, outsider_email, f"Globex {suffix}").json()["data"]

        response = client.get(
            f"/api/v1/organizations/{owner['organization']['id']}/members",
            headers={"Authorization": f"Bearer {outsider['access_token']}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    finally:
        _cleanup(suffix)
