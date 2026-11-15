"""HTTP authorization, validation, pagination, and tenant tests for comments."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.modules.agents.models import Agent
from app.modules.comments.models import MAX_COMMENT_LENGTH, Comment
from app.modules.posts.models import Post, PostStatus
from tests.test_agent_api import bearer, create_account, register_agent


def _agent_key(client: TestClient, token: str, agent_id: str) -> str:
    response = client.post(
        f"/api/v1/agents/{agent_id}/credentials",
        json={"label": "comment tests"},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["secret"]


def _create_post(sqlite_session_factory, organization_id: str, agent_id: str, **kwargs) -> Post:
    with sqlite_session_factory() as db:
        post = Post(
            organization_id=UUID(organization_id),
            author_agent_id=UUID(agent_id),
            title="A published update",
            content="A valid published post",
            status=PostStatus.PUBLISHED.value,
            published_at=datetime.now(UTC),
            **kwargs,
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        return post


def _post_comment(client: TestClient, post_id: str, key: str, content="Hello there"):
    return client.post(
        f"/api/v1/posts/{post_id}/comments",
        json={"content": content},
        headers={"Authorization": f"Bearer {key}"},
    )


def _create_agent_and_post(client, sqlite_session_factory, email, org_name):
    owner = create_account(client, email=email, organization_name=org_name)
    agent = register_agent(client, owner["access_token"], company_name=f"{org_name} Agent")
    key = _agent_key(client, owner["access_token"], agent["id"])
    post = _create_post(sqlite_session_factory, owner["organization"]["id"], agent["id"])
    return owner, agent, key, post


@patch("app.modules.posts.router.embed_and_publish.delay")
def test_agent_creates_comment_and_uses_authenticated_identity(
    delay, api_client, sqlite_session_factory
):
    owner, agent, key, post = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-owner@example.test", "Comment Org"
    )
    response = _post_comment(
        api_client,
        str(post.id),
        key,
        {
            "content": "  A useful response  ",
            "author_agent_id": str(uuid4()),
            "organization_id": str(uuid4()),
        },
    )
    assert response.status_code == 422  # Caller identity fields are forbidden.

    response = _post_comment(api_client, str(post.id), key, "  A useful response  ")
    assert response.status_code == 201, response.text
    comment = response.json()["data"]
    assert comment["organization_id"] == owner["organization"]["id"]
    assert comment["author_agent_id"] == agent["id"]
    assert comment["content"] == "A useful response"
    assert comment["author"] == {"id": agent["id"], "company_name": agent["company_name"]}
    assert "credential" not in response.text
    assert "webhook" not in response.text
    delay.assert_not_called()


def test_comment_authentication_and_content_validation(api_client, sqlite_session_factory):
    owner, agent, key, post = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-validation@example.test", "Validation"
    )
    assert (
        api_client.post(f"/api/v1/posts/{post.id}/comments", json={"content": "hello"}).status_code
        == 401
    )
    assert _post_comment(api_client, str(post.id), "asa_invalid", "hello").status_code == 401
    assert _post_comment(api_client, str(post.id), key, "  ").status_code == 422
    assert (
        _post_comment(api_client, str(post.id), key, "x" * (MAX_COMMENT_LENGTH + 1)).status_code
        == 422
    )
    accepted = _post_comment(api_client, str(post.id), key, "x" * MAX_COMMENT_LENGTH)
    assert accepted.status_code == 201


def test_cross_tenant_and_missing_post_comment_creation_are_not_found(
    api_client, sqlite_session_factory
):
    _, _, key_a, _ = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-a@example.test", "Org A"
    )
    _, _, _, post_b = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-b@example.test", "Org B"
    )
    assert _post_comment(api_client, str(post_b.id), key_a).status_code == 404
    assert _post_comment(api_client, str(uuid4()), key_a).status_code == 404


@pytest.mark.parametrize(
    "post_changes, expected_code",
    [
        ({"status": PostStatus.ARCHIVED.value}, "post_not_commentable"),
        ({"expires_at": datetime.now(UTC) - timedelta(days=1)}, "post_expired"),
    ],
)
def test_archived_and_expired_posts_reject_comments(
    api_client, sqlite_session_factory, post_changes, expected_code
):
    _, _, key, post = _create_agent_and_post(
        api_client,
        sqlite_session_factory,
        f"comment-ineligible-{expected_code}@example.test",
        "Ineligible",
    )
    with sqlite_session_factory() as db:
        stored = db.get(Post, post.id)
        for key_name, value in post_changes.items():
            setattr(stored, key_name, value)
        db.commit()
    response = _post_comment(api_client, str(post.id), key)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == expected_code


def test_inactive_agent_cannot_comment(api_client, sqlite_session_factory):
    owner, agent, key, post = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-inactive@example.test", "Inactive"
    )
    response = api_client.post(
        f"/api/v1/agents/{agent['id']}/status",
        json={"action": "suspend"},
        headers=bearer(owner["access_token"]),
    )
    assert response.status_code == 200
    assert _post_comment(api_client, str(post.id), key).status_code == 401


def test_comment_listing_is_tenant_scoped_paginated_chronological_and_safe(
    api_client, sqlite_session_factory
):
    owner_a, agent_a, key_a, post_a = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-list-a@example.test", "List A"
    )
    owner_b, _, _, _ = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-list-b@example.test", "List B"
    )
    with sqlite_session_factory() as db:
        author = db.get(Agent, UUID(agent_a["id"]))
        now = datetime.now(UTC)
        for i in range(3):
            db.add(
                Comment(
                    organization_id=UUID(owner_a["organization"]["id"]),
                    post_id=post_a.id,
                    author_agent_id=author.id,
                    content=f"Comment {i}",
                    created_at=now + timedelta(seconds=i),
                    updated_at=now + timedelta(seconds=i),
                )
            )
        db.commit()
    url = f"/api/v1/posts/{post_a.id}/comments?page=2&page_size=2"
    response = api_client.get(url, headers=bearer(owner_a["access_token"]))
    assert response.status_code == 200
    assert [row["content"] for row in response.json()["data"]] == ["Comment 2"]
    assert response.json()["meta"] == {"page": 2, "page_size": 2, "total": 3}
    assert response.json()["data"][0]["author"]["company_name"] == agent_a["company_name"]
    assert "credential_hash" not in response.text
    assert "webhook_secret" not in response.text
    cross_tenant = api_client.get(
        f"/api/v1/posts/{post_a.id}/comments", headers=bearer(owner_b["access_token"])
    )
    assert cross_tenant.status_code == 404
    agent_read = api_client.get(
        f"/api/v1/posts/{post_a.id}/comments", headers={"Authorization": f"Bearer {key_a}"}
    )
    assert agent_read.status_code == 200


def test_comment_author_can_delete_own_comment_but_not_other_agents_comment(
    api_client, sqlite_session_factory
):
    owner, author_agent, key, post = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-delete-a@example.test", "Delete A"
    )
    other_agent = register_agent(
        api_client, owner["access_token"], company_name="Other agent in same tenant"
    )
    other_key = _agent_key(api_client, owner["access_token"], other_agent["id"])
    other_owner, _, other_tenant_key, _ = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-delete-b@example.test", "Delete B"
    )
    created = _post_comment(api_client, str(post.id), key).json()["data"]
    assert (
        api_client.delete(
            f"/api/v1/comments/{created['id']}", headers={"Authorization": f"Bearer {other_key}"}
        ).status_code
        == 403
    )
    assert (
        api_client.delete(
            f"/api/v1/comments/{created['id']}",
            headers={"Authorization": f"Bearer {other_tenant_key}"},
        ).status_code
        == 404
    )
    deleted = api_client.delete(
        f"/api/v1/comments/{created['id']}", headers={"Authorization": f"Bearer {key}"}
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"id": created["id"], "deleted": True}
    assert created["author_agent_id"] == author_agent["id"]
    assert other_owner["organization"]["id"] != owner["organization"]["id"]


def test_owner_admin_may_delete_but_ordinary_member_cannot(api_client, sqlite_session_factory):
    owner, _, author_key, post = _create_agent_and_post(
        api_client, sqlite_session_factory, "comment-owner-delete@example.test", "Owner Delete"
    )
    first = _post_comment(api_client, str(post.id), author_key).json()["data"]
    owner_delete = api_client.delete(
        f"/api/v1/comments/{first['id']}", headers=bearer(owner["access_token"])
    )
    assert owner_delete.status_code == 200

    member = create_account(
        api_client, email="comment-member@example.test", organization_name="Member Own"
    )
    org_id = owner["organization"]["id"]
    added = api_client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "comment-member@example.test", "role": "member"},
        headers=bearer(owner["access_token"]),
    )
    assert added.status_code == 201
    login = api_client.post(
        "/api/v1/auth/login",
        json={"email": "comment-member@example.test", "password": "correct horse battery staple"},
    )
    member_token = login.json()["data"]["access_token"]
    switched = api_client.post(
        "/api/v1/organizations/switch",
        json={"organization_id": org_id},
        headers=bearer(member_token),
    )
    assert switched.status_code == 200
    second = _post_comment(api_client, str(post.id), author_key).json()["data"]
    forbidden = api_client.delete(f"/api/v1/comments/{second['id']}", headers=bearer(member_token))
    assert forbidden.status_code == 403
    create_account(api_client, email="comment-admin@example.test", organization_name="Admin Own")
    added_admin = api_client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "comment-admin@example.test", "role": "admin"},
        headers=bearer(owner["access_token"]),
    )
    assert added_admin.status_code == 201
    admin_login = api_client.post(
        "/api/v1/auth/login",
        json={"email": "comment-admin@example.test", "password": "correct horse battery staple"},
    )
    admin_token = admin_login.json()["data"]["access_token"]
    admin_switch = api_client.post(
        "/api/v1/organizations/switch",
        json={"organization_id": org_id},
        headers=bearer(admin_token),
    )
    assert admin_switch.status_code == 200
    assert (
        api_client.delete(
            f"/api/v1/comments/{second['id']}", headers=bearer(admin_token)
        ).status_code
        == 200
    )
    assert member["organization"]["id"] != org_id
