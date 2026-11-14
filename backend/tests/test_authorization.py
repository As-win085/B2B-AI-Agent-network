"""ASAMA-103: organization membership and role-based authorization."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ORGANIZATIONS = "/api/v1/organizations"
PASSWORD = "correct horse battery staple"


def create_account(
    client: TestClient,
    *,
    email: str,
    organization_name: str,
    organization_slug: str | None = None,
) -> dict[str, Any]:
    payload = {
        "email": email,
        "password": PASSWORD,
        "organization_name": organization_name,
        "organization_slug": organization_slug,
    }
    response = client.post(REGISTER, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def login(client: TestClient, email: str) -> dict[str, Any]:
    response = client.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def switch(client: TestClient, token: str, organization_id: str):
    return client.post(
        f"{ORGANIZATIONS}/switch",
        json={"organization_id": organization_id},
        headers=bearer(token),
    )


def add_member(
    client: TestClient,
    token: str,
    organization_id: str,
    *,
    email: str,
    role: str = "member",
):
    return client.post(
        f"{ORGANIZATIONS}/{organization_id}/members",
        json={"email": email, "role": role},
        headers=bearer(token),
    )


def test_list_organizations_returns_membership_roles(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")

    response = api_client.get(ORGANIZATIONS, headers=bearer(owner["access_token"]))

    assert response.status_code == 200
    organizations = response.json()["data"]
    assert len(organizations) == 1
    assert organizations[0]["slug"] == "acme"
    assert organizations[0]["role"] == "owner"


def test_organization_endpoints_require_authentication(api_client: TestClient) -> None:
    assert api_client.get(ORGANIZATIONS).status_code == 401
    assert api_client.get(f"{ORGANIZATIONS}/{uuid.uuid4()}/members").status_code == 401
    assert (
        api_client.patch(f"{ORGANIZATIONS}/{uuid.uuid4()}", json={"name": "X"}).status_code == 401
    )


def test_cross_tenant_access_is_reported_as_not_found(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    outsider = create_account(api_client, email="outsider@example.test", organization_name="Globex")
    acme_id = owner["organization"]["id"]

    token = outsider["access_token"]
    assert (
        api_client.get(f"{ORGANIZATIONS}/{acme_id}/members", headers=bearer(token)).status_code
        == 404
    )
    assert switch(api_client, token, acme_id).status_code == 404
    assert (
        api_client.patch(
            f"{ORGANIZATIONS}/{acme_id}", json={"name": "Hijacked"}, headers=bearer(token)
        ).status_code
        == 404
    )
    assert (
        api_client.delete(
            f"{ORGANIZATIONS}/{acme_id}/members/{uuid.uuid4()}", headers=bearer(token)
        ).status_code
        == 404
    )


def test_member_can_read_but_not_manage(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    member = create_account(api_client, email="member@example.test", organization_name="Member Co")
    acme_id = owner["organization"]["id"]

    added = add_member(
        api_client, owner["access_token"], acme_id, email="member@example.test", role="member"
    )
    assert added.status_code == 201
    assert added.json()["data"]["role"] == "member"

    member_login = login(api_client, "member@example.test")
    assert switch(api_client, member_login["access_token"], acme_id).status_code == 200
    token = member_login["access_token"]

    assert (
        api_client.get(f"{ORGANIZATIONS}/{acme_id}/members", headers=bearer(token)).status_code
        == 200
    )
    assert (
        api_client.patch(
            f"{ORGANIZATIONS}/{acme_id}", json={"name": "Renamed"}, headers=bearer(token)
        ).status_code
        == 403
    )
    assert add_member(api_client, token, acme_id, email="someone@example.test").status_code == 403
    assert (
        api_client.delete(
            f"{ORGANIZATIONS}/{acme_id}/members/{added.json()['data']['id']}",
            headers=bearer(token),
        ).status_code
        == 403
    )
    assert member["organization"]["id"] != acme_id


def test_admin_can_rename_and_manage_members_but_not_grant_admin(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    admin_user = create_account(
        api_client, email="admin@example.test", organization_name="Admin Co"
    )
    candidate = create_account(
        api_client, email="candidate@example.test", organization_name="Candidate Co"
    )
    acme_id = owner["organization"]["id"]

    granted = add_member(
        api_client, owner["access_token"], acme_id, email="admin@example.test", role="admin"
    )
    assert granted.status_code == 201
    assert granted.json()["data"]["role"] == "admin"

    admin_token = login(api_client, "admin@example.test")["access_token"]
    assert switch(api_client, admin_token, acme_id).status_code == 200

    renamed = api_client.patch(
        f"{ORGANIZATIONS}/{acme_id}", json={"name": "Acme Renamed"}, headers=bearer(admin_token)
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["name"] == "Acme Renamed"

    cannot_grant_admin = add_member(
        api_client, admin_token, acme_id, email="candidate@example.test", role="admin"
    )
    assert cannot_grant_admin.status_code == 403

    can_add_member = add_member(
        api_client, admin_token, acme_id, email="candidate@example.test", role="member"
    )
    assert can_add_member.status_code == 201
    member_id = can_add_member.json()["data"]["id"]

    removed = api_client.delete(
        f"{ORGANIZATIONS}/{acme_id}/members/{member_id}", headers=bearer(admin_token)
    )
    assert removed.status_code == 200
    assert candidate["organization"]["id"] != acme_id
    assert admin_user["organization"]["id"] != acme_id


def test_owner_protection_and_admin_removal_rules(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    create_account(api_client, email="admin@example.test", organization_name="Admin Co")
    acme_id = owner["organization"]["id"]

    admin_membership = add_member(
        api_client, owner["access_token"], acme_id, email="admin@example.test", role="admin"
    )
    assert admin_membership.status_code == 201
    admin_member_id = admin_membership.json()["data"]["id"]

    # The owner membership itself cannot be removed.
    members = api_client.get(
        f"{ORGANIZATIONS}/{acme_id}/members", headers=bearer(owner["access_token"])
    ).json()["data"]
    owner_membership = next(member for member in members if member["role"] == "owner")
    protected = api_client.delete(
        f"{ORGANIZATIONS}/{acme_id}/members/{owner_membership['id']}",
        headers=bearer(owner["access_token"]),
    )
    assert protected.status_code == 403
    assert protected.json()["error"]["code"] == "owner_protected"

    # An admin cannot remove another admin.
    admin_token = login(api_client, "admin@example.test")["access_token"]
    assert switch(api_client, admin_token, acme_id).status_code == 200
    self_removal = api_client.delete(
        f"{ORGANIZATIONS}/{acme_id}/members/{admin_member_id}", headers=bearer(admin_token)
    )
    assert self_removal.status_code == 403

    # The owner can.
    removed = api_client.delete(
        f"{ORGANIZATIONS}/{acme_id}/members/{admin_member_id}",
        headers=bearer(owner["access_token"]),
    )
    assert removed.status_code == 200


def test_switching_organization_updates_current_context(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")
    second = create_account(api_client, email="second@example.test", organization_name="Globex")
    second_org_id = second["organization"]["id"]

    added = add_member(
        api_client,
        second["access_token"],
        second_org_id,
        email="owner@example.test",
        role="member",
    )
    assert added.status_code == 201

    token = login(api_client, "owner@example.test")["access_token"]
    before = api_client.get("/api/v1/auth/me", headers=bearer(token)).json()["data"]
    assert before["organization"]["id"] == owner["organization"]["id"]

    switched = switch(api_client, token, second_org_id)
    assert switched.status_code == 200
    assert switched.json()["data"]["organization"]["role"] == "member"

    after = api_client.get("/api/v1/auth/me", headers=bearer(token)).json()["data"]
    assert after["organization"]["id"] == second_org_id
    assert after["organization"]["role"] == "member"


def test_adding_unknown_user_returns_not_found(api_client: TestClient) -> None:
    owner = create_account(api_client, email="owner@example.test", organization_name="Acme")

    response = add_member(
        api_client,
        owner["access_token"],
        owner["organization"]["id"],
        email="ghost@example.test",
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"
