"""HTTP-level tests for post publishing and tenant isolation."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_agent_api import bearer, create_account, register_agent


def _agent_key(client: TestClient, token: str, agent_id: str) -> str:
    response = client.post(
        f"/api/v1/agents/{agent_id}/credentials",
        json={"label": "post tests"},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["secret"]


def _publish(client: TestClient, key: str, body: dict[str, Any] | None = None):
    return client.post(
        "/api/v1/posts",
        json=body or {"title": "A useful update", "content": "An interesting business post."},
        headers={"Authorization": f"Bearer {key}"},
    )


@patch("app.modules.posts.router.embed_and_publish.delay")
def test_create_post_uses_authenticated_agent_and_processing_status(delay, api_client: TestClient):
    owner = create_account(api_client, email="post-owner@example.test", organization_name="Posts")
    agent = register_agent(api_client, owner["access_token"])
    key = _agent_key(api_client, owner["access_token"], agent["id"])

    response = _publish(api_client, key)

    assert response.status_code == 202, response.text
    post = response.json()["data"]
    assert post["author_agent_id"] == agent["id"]
    assert post["organization_id"] == owner["organization"]["id"]
    assert post["status"] == "processing"
    assert "embedding" not in post
    assert "secret" not in response.text
    delay.assert_called_once_with(post["id"], 1)


@patch("app.modules.posts.router.embed_and_publish.delay")
def test_create_post_rejects_forged_author_and_requires_agent_auth(delay, api_client: TestClient):
    owner = create_account(api_client, email="posts-forge@example.test", organization_name="Forge")
    agent = register_agent(api_client, owner["access_token"])
    key = _agent_key(api_client, owner["access_token"], agent["id"])
    r = _publish(
        api_client,
        key,
        {"title": "Hello", "content": "World", "author_agent_id": "x"},
    )
    assert r.status_code == 422
    assert (
        api_client.post("/api/v1/posts", json={"title": "Hello", "content": "World"}).status_code
        == 401
    )
    delay.assert_not_called()


@patch("app.modules.posts.router.embed_and_publish.delay")
def test_list_is_organization_scoped_and_paged(delay, api_client: TestClient):
    a = create_account(api_client, email="posts-a@example.test", organization_name="A")
    b = create_account(api_client, email="posts-b@example.test", organization_name="B")
    agent_a = register_agent(api_client, a["access_token"])
    agent_b = register_agent(api_client, b["access_token"])
    key_a = _agent_key(api_client, a["access_token"], agent_a["id"])
    key_b = _agent_key(api_client, b["access_token"], agent_b["id"])
    post_a = _publish(api_client, key_a).json()["data"]
    _publish(api_client, key_b)

    result = api_client.get("/api/v1/posts?page=1&page_size=1", headers=bearer(a["access_token"]))
    assert result.status_code == 200
    assert [p["id"] for p in result.json()["data"]] == [post_a["id"]]
    assert result.json()["meta"] == {"page": 1, "page_size": 1, "total": 1}
    assert (
        api_client.get(
            f"/api/v1/posts/{post_a['id']}", headers=bearer(b["access_token"])
        ).status_code
        == 404
    )
    delay.assert_called()


@patch("app.modules.posts.router.embed_and_publish.delay")
def test_credentials_revoked_before_post_authentication(delay, api_client: TestClient):
    owner = create_account(
        api_client, email="posts-revoke@example.test", organization_name="Revoke"
    )
    agent = register_agent(api_client, owner["access_token"])
    key = _agent_key(api_client, owner["access_token"], agent["id"])
    credentials = api_client.get(
        f"/api/v1/agents/{agent['id']}/credentials", headers=bearer(owner["access_token"])
    ).json()["data"]
    revoked = api_client.delete(
        f"/api/v1/agents/{agent['id']}/credentials/{credentials[0]['id']}",
        headers=bearer(owner["access_token"]),
    )
    assert revoked.status_code == 200
    assert _publish(api_client, key).status_code == 401
    delay.assert_not_called()


@patch("app.modules.posts.router.embed_and_publish.delay")
def test_author_can_edit_only_own_post_and_archive_is_admin_only(delay, api_client: TestClient):
    owner = create_account(api_client, email="posts-edit@example.test", organization_name="Edit")
    agent = register_agent(api_client, owner["access_token"])
    key = _agent_key(api_client, owner["access_token"], agent["id"])
    post = _publish(api_client, key).json()["data"]
    changed = api_client.patch(
        f"/api/v1/posts/{post['id']}",
        json={"content": "Updated post content"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert changed.status_code == 202
    assert changed.json()["data"]["status"] == "processing"
    assert changed.json()["data"]["author_agent_id"] == agent["id"]
    archived = api_client.delete(
        f"/api/v1/posts/{post['id']}", headers=bearer(owner["access_token"])
    )
    assert archived.status_code == 200
    assert archived.json()["data"]["status"] == "archived"
    assert delay.call_count == 2
