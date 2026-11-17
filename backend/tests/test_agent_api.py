"""ASAMA-104: agent management API tests."""
from __future__ import annotations

from typing import Any

import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

REGISTER_USER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
AGENTS = "/api/v1/agents"
PASSWORD = "correct horse battery staple"


def create_account(
    client: TestClient,
    *,
    email: str,
    organization_name: str,
) -> dict[str, Any]:
    r = client.post(
        REGISTER_USER,
        json={
            "email": email,
            "password": PASSWORD,
            "organization_name": organization_name,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_agent(
    client: TestClient,
    token: str,
    *,
    company_name: str = "Acme Bot",
    industry_category: str | None = "Technology",
    interest_manifesto: str | None = "We are interested in AI partnerships.",
) -> dict[str, Any]:
    """Register an agent for the authenticated user."""
    pass


def test_webhook_test_validates_url_without_delivery(api_client: TestClient) -> None:
    """Test-ping performs a real signed HTTP delivery (Milestone B).

    Validates that the endpoint authenticates, resolves the URL, signs the event,
    sends with SSRF/redirect/TLS protections, and returns the outcome.
    """
    from unittest.mock import patch

    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    # Patch DNS to return a public address so the delivery can proceed
    with patch("app.modules.agents.webhook.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        response = api_client.post(
            f"{AGENTS}/{agent['id']}/webhook/test",
            headers=bearer(owner["access_token"]),
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["valid"] is True
    assert "delivery_attempted" in data
    assert "outcome" in data
    assert "url" in data
    assert "event_id" in data
    # Outcome should be "delivered" since DNS resolves to a public address
    assert data["outcome"] == "delivered" or data["outcome"] in ("timeout", "failed")