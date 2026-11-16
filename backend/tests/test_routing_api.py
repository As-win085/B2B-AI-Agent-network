"""Routing activity APIs, agent blocks and embedding enqueue hooks."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.modules.posts.models import Post, PostStatus
from app.modules.routing.models import RoutingLog

REGISTER_USER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
AGENTS = "/api/v1/agents"
AGENT_BLOCKS = "/api/v1/agent-blocks"
PASSWORD = "correct horse battery staple"


def _register(client: TestClient, *, email: str, organization_name: str) -> dict[str, Any]:
    response = client.post(
        REGISTER_USER,
        json={"email": email, "password": PASSWORD, "organization_name": organization_name},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_agent(
    client: TestClient, token: str, *, manifesto: str | None = "interests"
) -> dict[str, Any]:
    response = client.post(
        AGENTS,
        json={
            "company_name": "Routing Bot",
            "industry_category": "Technology",
            "interest_manifesto": manifesto,
        },
        headers=_bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _seed_post(
    db: Session, *, organization_id: str, author_agent_id: str, title: str = "Seeded post"
) -> Post:
    post = Post(
        organization_id=UUID(organization_id),
        author_agent_id=UUID(author_agent_id),
        title=title,
        content="Seeded content.",
        status=PostStatus.PUBLISHED.value,
        embedding=[0.5, 0.5],
        embedding_provider="openai",
        embedding_model="test-model",
        embedding_generation=1,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def _seed_log(
    db: Session,
    *,
    post: Post,
    agent_id: UUID,
    decision: str = "selected",
    rank: int | None = 1,
) -> RoutingLog:
    log = RoutingLog(
        organization_id=post.organization_id,
        post_id=post.id,
        agent_id=agent_id,
        similarity_score=0.91,
        rerank_score=0.87 if decision == "selected" else None,
        rank=rank,
        decision=decision,
        decision_reason="meets_threshold" if decision == "selected" else "below_threshold",
        embedding_provider="openai",
        embedding_model="test-model",
        embedding_generation=1,
        reranker_provider="cohere" if decision == "selected" else None,
        reranker_model="rerank-test" if decision == "selected" else None,
        rerank_status="completed" if decision == "selected" else "skipped_unconfigured",
    )
    db.add(log)
    db.commit()
    return log


def test_post_routing_logs_are_organization_scoped(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    agent = _register_agent(api_client, owner["access_token"])
    agent_b = _register_agent(api_client, owner["access_token"])
    other = _register(api_client, email="other@example.test", organization_name="Other")

    with sqlite_session_factory() as db:
        post = _seed_post(
            db,
            organization_id=owner["organization"]["id"],
            author_agent_id=agent["id"],
        )
        post_id = str(post.id)  # capture before the session closes (expiry)
        _seed_log(db, post=post, agent_id=UUID(agent["id"]))
        _seed_log(
            db,
            post=post,
            agent_id=UUID(agent_b["id"]),
            decision="rejected",
            rank=None,
        )

    url = f"/api/v1/posts/{post_id}/routing-logs"
    response = api_client.get(url, headers=_bearer(owner["access_token"]))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"] == {"page": 1, "page_size": 20, "total": 2}
    assert len(payload["data"]) == 2
    entry = next(item for item in payload["data"] if item["decision"] == "selected")
    assert entry["similarity_score"] == 0.91
    assert entry["rerank_score"] == 0.87
    assert entry["rerank_status"] == "completed"
    assert entry["embedding_model"] == "test-model"
    assert entry["embedding_generation"] == 1
    assert entry["decision_reason"] == "meets_threshold"

    # Pagination reduces the page but not the reported total.
    paged = api_client.get(url, params={"page_size": 1}, headers=_bearer(owner["access_token"]))
    assert len(paged.json()["data"]) == 1
    assert paged.json()["meta"]["total"] == 2

    # Another tenant cannot read the log at all (404, not 403 — no leak).
    cross = api_client.get(url, headers=_bearer(other["access_token"]))
    assert cross.status_code == 404

    # Authentication is required.
    assert api_client.get(url).status_code == 401

    # A non-existent post is also 404.
    missing = api_client.get(
        "/api/v1/posts/00000000-0000-0000-0000-000000000000/routing-logs",
        headers=_bearer(owner["access_token"]),
    )
    assert missing.status_code == 404


def test_agent_routing_logs_expose_activity_about_own_agent_only(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    agent = _register_agent(api_client, owner["access_token"])
    other = _register(api_client, email="other@example.test", organization_name="Other")
    other_agent = _register_agent(api_client, other["access_token"])

    with sqlite_session_factory() as db:
        # A post published by the OTHER tenant routed to our agent: activity
        # about our agent stays visible to our organization.
        foreign_post = _seed_post(
            db,
            organization_id=other["organization"]["id"],
            author_agent_id=other_agent["id"],
        )
        foreign_post_id = str(foreign_post.id)  # capture before session close
        _seed_log(db, post=foreign_post, agent_id=UUID(agent["id"]))
        # And one of our own posts routed to the other tenant's agent.
        own_post = _seed_post(
            db,
            organization_id=owner["organization"]["id"],
            author_agent_id=agent["id"],
        )
        _seed_log(db, post=own_post, agent_id=UUID(other_agent["id"]))

    url = f"/api/v1/agents/{agent['id']}/routing-logs"
    response = api_client.get(url, headers=_bearer(owner["access_token"]))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert payload["data"][0]["post_id"] == foreign_post_id
    assert payload["data"][0]["organization_id"] == other["organization"]["id"]

    # The other tenant cannot read routing activity about our agent.
    cross = api_client.get(url, headers=_bearer(other["access_token"]))
    assert cross.status_code == 404

    # Our tenant's log about their agent is invisible to them through this
    # endpoint (it is activity about our agent's decision record).
    assert (
        api_client.get(
            f"/api/v1/agents/{other_agent['id']}/routing-logs",
            headers=_bearer(owner["access_token"]),
        ).status_code
        == 404
    )
    assert api_client.get(url).status_code == 401


def _flatten_routes(routes: list[Any]) -> list[Any]:
    """Flatten FastAPI's lazy ``_IncludedRouter`` wrappers into APIRoutes."""
    flat: list[Any] = []
    for route in routes:
        inner = getattr(route, "routes", None) or getattr(
            getattr(route, "original_router", None), "routes", None
        )
        if inner:
            flat.extend(_flatten_routes(inner))
        else:
            flat.append(route)
    return flat


def test_no_client_endpoint_triggers_routing(api_client: TestClient) -> None:
    all_routes = _flatten_routes(list(api_client.app.routes))
    triggering = [
        (sorted(route.methods), route.path)
        for route in all_routes
        if hasattr(route, "methods") and "routing" in route.path
    ]
    assert triggering, "routing-log endpoints should be registered"
    for methods, path in triggering:
        assert "POST" not in methods and "PUT" not in methods and "PATCH" not in methods, (
            f"routing must not be triggerable by clients: {methods} {path}"
        )


def test_agent_registration_and_manifesto_updates_enqueue_embedding(
    api_client: TestClient,
) -> None:
    with patch("app.modules.agents.router.embed_manifesto") as task:
        owner = _register(api_client, email="owner@example.test", organization_name="Acme")
        agent = _register_agent(api_client, owner["access_token"], manifesto="First interests.")
        task.delay.assert_called_once_with(agent["id"], 1)

        # Manifesto change bumps the generation and re-enqueues.
        response = api_client.patch(
            f"{AGENTS}/{agent['id']}/manifesto",
            json={"interest_manifesto": "Second interests."},
            headers=_bearer(owner["access_token"]),
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["embedding_generation"] == 2
        assert task.delay.call_args.args == (agent["id"], 2)

        # An unchanged manifesto does not bump the generation, but the
        # idempotent task is still enqueued with the current generation.
        response = api_client.patch(
            f"{AGENTS}/{agent['id']}/manifesto",
            json={"interest_manifesto": "Second interests."},
            headers=_bearer(owner["access_token"]),
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["embedding_generation"] == 2
        assert task.delay.call_count == 3
        assert task.delay.call_args.args == (agent["id"], 2)

        # Partial profile updates enqueue only when a manifesto is provided.
        api_client.patch(
            f"{AGENTS}/{agent['id']}",
            json={"company_name": "Renamed Bot"},
            headers=_bearer(owner["access_token"]),
        )
        assert task.delay.call_count == 3

        api_client.patch(
            f"{AGENTS}/{agent['id']}",
            json={"interest_manifesto": "Third interests."},
            headers=_bearer(owner["access_token"]),
        )
        assert task.delay.call_count == 4
        assert task.delay.call_args.args == (agent["id"], 3)


def test_registration_without_manifesto_does_not_enqueue(
    api_client: TestClient,
) -> None:
    with patch("app.modules.agents.router.embed_manifesto") as task:
        owner = _register(api_client, email="owner@example.test", organization_name="Acme")
        _register_agent(api_client, owner["access_token"], manifesto=None)
        task.delay.assert_not_called()


def test_agent_blocks_api_is_admin_scoped_and_tenant_scoped(
    api_client: TestClient,
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    other = _register(api_client, email="other@example.test", organization_name="Other")
    other_agent = _register_agent(api_client, other["access_token"])

    # Owner blocks an agent owned by another tenant (cross-org policy).
    created = api_client.post(
        AGENT_BLOCKS,
        json={"blocked_agent_id": other_agent["id"], "reason": "spam"},
        headers=_bearer(owner["access_token"]),
    )
    assert created.status_code == 201, created.text
    block = created.json()["data"]
    assert block["blocked_agent_id"] == other_agent["id"]
    assert block["organization_id"] == owner["organization"]["id"]
    assert block["reason"] == "spam"

    # Duplicate block is a conflict.
    duplicate = api_client.post(
        AGENT_BLOCKS,
        json={"blocked_agent_id": other_agent["id"]},
        headers=_bearer(owner["access_token"]),
    )
    assert duplicate.status_code == 409

    # Unknown agent cannot be blocked.
    missing = api_client.post(
        AGENT_BLOCKS,
        json={"blocked_agent_id": "00000000-0000-0000-0000-000000000000"},
        headers=_bearer(owner["access_token"]),
    )
    assert missing.status_code == 404

    # Lists are tenant-scoped: the other tenant sees no blocks.
    listed = api_client.get(AGENT_BLOCKS, headers=_bearer(owner["access_token"]))
    assert listed.status_code == 200
    assert [item["blocked_agent_id"] for item in listed.json()["data"]] == [other_agent["id"]]
    other_listed = api_client.get(AGENT_BLOCKS, headers=_bearer(other["access_token"]))
    assert other_listed.json()["data"] == []

    # The other tenant cannot delete a block it does not own (404).
    foreign_delete = api_client.delete(
        f"{AGENT_BLOCKS}/{other_agent['id']}", headers=_bearer(other["access_token"])
    )
    assert foreign_delete.status_code == 404
    assert api_client.get(AGENT_BLOCKS, headers=_bearer(owner["access_token"])).json()["data"] != []

    # Unauthenticated and member-role access are refused.
    assert api_client.get(AGENT_BLOCKS).status_code == 401
    member = _register(api_client, email="member@example.test", organization_name="Member Co")
    api_client.post(
        f"/api/v1/organizations/{owner['organization']['id']}/members",
        json={"email": "member@example.test", "role": "member"},
        headers=_bearer(owner["access_token"]),
    )
    login = api_client.post(LOGIN, json={"email": "member@example.test", "password": PASSWORD})
    member_token = login.json()["data"]["access_token"]
    assert member["organization"]["id"] != owner["organization"]["id"]
    # Switch the member's active organization to Acme, where they hold the
    # member role (and therefore no block-management permission).
    api_client.post(
        "/api/v1/organizations/switch",
        json={"organization_id": owner["organization"]["id"]},
        headers=_bearer(member_token),
    )
    forbidden = api_client.post(
        AGENT_BLOCKS,
        json={"blocked_agent_id": other_agent["id"]},
        headers=_bearer(member_token),
    )
    assert forbidden.status_code == 403

    # Owner can unblock; a second delete is 404.
    removed = api_client.delete(
        f"{AGENT_BLOCKS}/{other_agent['id']}", headers=_bearer(owner["access_token"])
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"]["blocked_agent_id"] == other_agent["id"]
    again = api_client.delete(
        f"{AGENT_BLOCKS}/{other_agent['id']}", headers=_bearer(owner["access_token"])
    )
    assert again.status_code == 404
