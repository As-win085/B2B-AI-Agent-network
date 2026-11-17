"""ASAMA-104: agent management API tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

REGISTER_USER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
AGENTS = "/api/v1/agents"
PASSWORD = "correct horse battery staple"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    r = client.post(
        AGENTS,
        json={
            "company_name": company_name,
            "industry_category": industry_category,
            "interest_manifesto": interest_manifesto,
        },
        headers=bearer(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_agent_returns_201(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])

    assert agent["company_name"] == "Acme Bot"
    assert agent["industry_category"] == "Technology"
    assert agent["status"] == "active"
    assert agent["webhook_configured"] is False
    assert "id" in agent
    assert agent["organization_id"] == owner["organization"]["id"]


def test_register_agent_requires_authentication(api_client: TestClient) -> None:
    r = api_client.post(AGENTS, json={"company_name": "Bot"})
    assert r.status_code == 401


def test_register_agent_requires_admin_or_owner(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    create_account(api_client, email="member@example.test", organization_name="Other")

    # Add member to Acme with member role.
    org_id = owner["organization"]["id"]
    api_client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "member@example.test", "role": "member"},
        headers=bearer(owner["access_token"]),
    )
    # Switch member's active org to Acme.
    login_r = api_client.post(LOGIN, json={"email": "member@example.test", "password": PASSWORD})
    member_token = login_r.json()["data"]["access_token"]
    api_client.post(
        "/api/v1/organizations/switch",
        json={"organization_id": org_id},
        headers=bearer(member_token),
    )

    r = api_client.post(
        AGENTS,
        json={"company_name": "Bot"},
        headers=bearer(member_token),
    )
    assert r.status_code == 403


def test_register_agent_rejects_blank_company_name(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    r = api_client.post(
        AGENTS,
        json={"company_name": "   "},
        headers=bearer(owner["access_token"]),
    )
    assert r.status_code == 422


def test_multiple_agents_per_organization(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    token = owner["access_token"]
    register_agent(api_client, token, company_name="Bot A")
    register_agent(api_client, token, company_name="Bot B")

    r = api_client.get(AGENTS, headers=bearer(token))
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------


def test_list_agents_scoped_to_organization(api_client: TestClient) -> None:
    owner_a = create_account(api_client, email="a@example.test", organization_name="Org A")
    owner_b = create_account(api_client, email="b@example.test", organization_name="Org B")

    register_agent(api_client, owner_a["access_token"], company_name="A Bot")
    register_agent(api_client, owner_b["access_token"], company_name="B Bot")

    r = api_client.get(AGENTS, headers=bearer(owner_a["access_token"]))
    names = [a["company_name"] for a in r.json()["data"]]
    assert names == ["A Bot"]


def test_get_agent_cross_tenant_returns_404(api_client: TestClient) -> None:
    owner_a = create_account(api_client, email="a@example.test", organization_name="Org A")
    owner_b = create_account(api_client, email="b@example.test", organization_name="Org B")

    agent = register_agent(api_client, owner_a["access_token"])
    r = api_client.get(f"{AGENTS}/{agent['id']}", headers=bearer(owner_b["access_token"]))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_agent_profile(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])

    r = api_client.patch(
        f"{AGENTS}/{agent['id']}",
        json={"company_name": "Updated Bot", "industry_category": "Finance"},
        headers=bearer(owner["access_token"]),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["company_name"] == "Updated Bot"
    assert data["industry_category"] == "Finance"


def test_update_manifesto(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])

    r = api_client.patch(
        f"{AGENTS}/{agent['id']}/manifesto",
        json={"interest_manifesto": "New manifesto content."},
        headers=bearer(owner["access_token"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["interest_manifesto"] == "New manifesto content."


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_suspend_and_reactivate_agent(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    token = owner["access_token"]

    r = api_client.post(
        f"{AGENTS}/{agent['id']}/status",
        json={"action": "suspend"},
        headers=bearer(token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "suspended"

    r = api_client.post(
        f"{AGENTS}/{agent['id']}/status",
        json={"action": "reactivate"},
        headers=bearer(token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "active"


def test_deactivate_agent(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])

    r = api_client.delete(f"{AGENTS}/{agent['id']}", headers=bearer(owner["access_token"]))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "deactivated"


def test_deactivated_agent_cannot_be_suspended(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    token = owner["access_token"]

    api_client.delete(f"{AGENTS}/{agent['id']}", headers=bearer(token))

    r = api_client.post(
        f"{AGENTS}/{agent['id']}/status",
        json={"action": "suspend"},
        headers=bearer(token),
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_issue_credential_returns_secret_once(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])

    r = api_client.post(
        f"{AGENTS}/{agent['id']}/credentials",
        json={"label": "prod-key"},
        headers=bearer(owner["access_token"]),
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["secret"].startswith("asa_")
    assert data["credential"]["label"] == "prod-key"
    assert data["credential"]["is_active"] is True
    # Secret must not appear in the credential metadata.
    assert data["secret"] not in str(data["credential"])


def test_credential_rotation_revokes_previous_key(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    headers = bearer(owner["access_token"])
    original = api_client.post(f"{AGENTS}/{agent['id']}/credentials", json={}, headers=headers)
    original_key = original.json()["data"]["secret"]

    replacement = api_client.post(
        f"{AGENTS}/{agent['id']}/credentials", json={"rotate": True}, headers=headers
    )
    replacement_key = replacement.json()["data"]["secret"]
    assert api_client.get("/api/v1/agents/me", headers=bearer(original_key)).status_code == 401
    assert api_client.get("/api/v1/agents/me", headers=bearer(replacement_key)).status_code == 200


def test_agent_credential_authenticates_machine_identity(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    issued = api_client.post(
        f"{AGENTS}/{agent['id']}/credentials", json={}, headers=bearer(owner["access_token"])
    ).json()["data"]

    response = api_client.get("/api/v1/agents/me", headers=bearer(issued["secret"]))
    assert response.status_code == 200
    assert response.json()["data"]["id"] == agent["id"]

    rejected = api_client.get("/api/v1/agents/me", headers=bearer("asa_invalid"))
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "invalid_agent_credential"


def test_agent_credential_rejected_after_suspension(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    issued = api_client.post(
        f"{AGENTS}/{agent['id']}/credentials", json={}, headers=bearer(owner["access_token"])
    ).json()["data"]
    api_client.post(
        f"{AGENTS}/{agent['id']}/status",
        json={"action": "suspend"},
        headers=bearer(owner["access_token"]),
    )
    response = api_client.get("/api/v1/agents/me", headers=bearer(issued["secret"]))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "agent_not_active"


def test_list_credentials_does_not_expose_secrets(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    token = owner["access_token"]

    issued = api_client.post(
        f"{AGENTS}/{agent['id']}/credentials",
        json={},
        headers=bearer(token),
    ).json()["data"]

    r = api_client.get(f"{AGENTS}/{agent['id']}/credentials", headers=bearer(token))
    assert r.status_code == 200
    creds = r.json()["data"]
    assert len(creds) == 1
    assert "secret" not in creds[0]
    assert issued["secret"] not in str(creds[0])


def test_revoke_credential_stops_authentication(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    token = owner["access_token"]

    issued = api_client.post(
        f"{AGENTS}/{agent['id']}/credentials",
        json={},
        headers=bearer(token),
    ).json()["data"]
    cred_id = issued["credential"]["id"]
    raw_secret = issued["secret"]

    r = api_client.delete(
        f"{AGENTS}/{agent['id']}/credentials/{cred_id}",
        headers=bearer(token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["revoked_at"] is not None

    rejected = api_client.get("/api/v1/agents/me", headers=bearer(raw_secret))
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "invalid_agent_credential"
    creds = api_client.get(f"{AGENTS}/{agent['id']}/credentials", headers=bearer(token)).json()[
        "data"
    ]
    assert creds[0]["revoked_at"] is not None
    assert creds[0]["is_active"] is False


def test_revoke_already_revoked_credential_returns_409(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    token = owner["access_token"]

    issued = api_client.post(
        f"{AGENTS}/{agent['id']}/credentials", json={}, headers=bearer(token)
    ).json()["data"]
    cred_id = issued["credential"]["id"]

    api_client.delete(f"{AGENTS}/{agent['id']}/credentials/{cred_id}", headers=bearer(token))
    r = api_client.delete(f"{AGENTS}/{agent['id']}/credentials/{cred_id}", headers=bearer(token))
    assert r.status_code == 409


def test_deactivate_agent_revokes_all_credentials(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    token = owner["access_token"]

    api_client.post(f"{AGENTS}/{agent['id']}/credentials", json={}, headers=bearer(token))
    api_client.post(f"{AGENTS}/{agent['id']}/credentials", json={}, headers=bearer(token))

    api_client.delete(f"{AGENTS}/{agent['id']}", headers=bearer(token))

    creds = api_client.get(f"{AGENTS}/{agent['id']}/credentials", headers=bearer(token)).json()[
        "data"
    ]
    assert all(c["revoked_at"] is not None for c in creds)


def test_cannot_issue_credential_for_suspended_agent(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    token = owner["access_token"]

    api_client.post(
        f"{AGENTS}/{agent['id']}/status", json={"action": "suspend"}, headers=bearer(token)
    )
    r = api_client.post(f"{AGENTS}/{agent['id']}/credentials", json={}, headers=bearer(token))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def test_configure_webhook_returns_signing_secret_once(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])

    with patch("app.modules.agents.webhook.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 443))]
        r = api_client.put(
            f"{AGENTS}/{agent['id']}/webhook",
            json={"webhook_url": "https://example.com/hook"},
            headers=bearer(owner["access_token"]),
        )

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["webhook_url"] == "https://example.com/hook"
    assert data["webhook_configured"] is True
    assert data["signing_secret"] is not None
    assert len(data["signing_secret"]) == 64  # 32 bytes hex


def test_configure_webhook_rotate_secret(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    token = owner["access_token"]

    with patch("app.modules.agents.webhook.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 443))]
        first = api_client.put(
            f"{AGENTS}/{agent['id']}/webhook",
            json={"webhook_url": "https://example.com/hook"},
            headers=bearer(token),
        ).json()["data"]["signing_secret"]

        second = api_client.put(
            f"{AGENTS}/{agent['id']}/webhook",
            json={"webhook_url": "https://example.com/hook", "rotate_secret": True},
            headers=bearer(token),
        ).json()["data"]["signing_secret"]

    assert first != second


def test_configure_webhook_ssrf_blocked(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])

    r = api_client.put(
        f"{AGENTS}/{agent['id']}/webhook",
        json={"webhook_url": "http://169.254.169.254/latest/meta-data/"},
        headers=bearer(owner["access_token"]),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("ssrf_blocked", "invalid_webhook_url")


def test_webhook_test_requires_configured_url(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])

    r = api_client.post(
        f"{AGENTS}/{agent['id']}/webhook/test",
        headers=bearer(owner["access_token"]),
    )
    assert r.status_code == 409


def test_webhook_test_validates_url_without_delivery(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    agent = register_agent(api_client, owner["access_token"])
    with patch("app.modules.agents.webhook.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 443))]
        api_client.put(
            f"{AGENTS}/{agent['id']}/webhook",
            json={"webhook_url": "https://example.com/hook"},
            headers=bearer(owner["access_token"]),
        )
        response = api_client.post(
            f"{AGENTS}/{agent['id']}/webhook/test", headers=bearer(owner["access_token"])
        )
    assert response.status_code == 200
    assert response.json()["data"] == {
        "valid": True,
        "delivery_attempted": False,
        "url": "https://example.com/hook",
    }
