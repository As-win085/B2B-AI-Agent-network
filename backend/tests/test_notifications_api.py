"""Notification delivery status and retry APIs: envelope, isolation, auth."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.modules.webhooks.models import WebhookDelivery

REGISTER_USER = "/api/v1/auth/register"
NOTIFICATIONS = "/api/v1/notifications"
PASSWORD = "correct horse battery staple"


def _register(client: TestClient, *, email: str, organization_name: str) -> dict:
    response = client.post(
        REGISTER_USER,
        json={"email": email, "password": PASSWORD, "organization_name": organization_name},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_agent(client: TestClient, token: str) -> dict:
    response = client.post(
        "/api/v1/agents",
        json={"company_name": "Agents Inc", "interest_manifesto": "logistics and freight"},
        headers=_bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _seed_delivery(
    db: Session,
    *,
    organization_id,
    post_id,
    agent_id,
    status: str = "pending",
    attempts: int = 0,
    delivered_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
) -> WebhookDelivery:
    delivery = WebhookDelivery(
        event_id=uuid4(),
        organization_id=organization_id,
        post_id=post_id,
        recipient_agent_id=agent_id,
        event_type="post.published",
        payload={"event_id": str(uuid4()), "data": {"post": {}}},
        url="https://example.com/hook",
        status=status,
        attempts=attempts,
        delivered_at=delivered_at,
        next_attempt_at=next_attempt_at,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def _seed_post(db: Session, *, organization_id, author_agent_id):
    from app.modules.posts.models import Post, PostStatus

    post = Post(
        organization_id=organization_id,
        author_agent_id=author_agent_id,
        title="Notification post",
        content="Content that produced a notification.",
        status=PostStatus.PUBLISHED.value,
        embedding_generation=1,
        published_at=datetime.now(UTC),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def test_notifications_require_authentication(api_client: TestClient) -> None:
    response = api_client.get(NOTIFICATIONS)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_list_shows_sent_and_received_but_never_other_tenants(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    other = _register(api_client, email="other@example.test", organization_name="Other")
    our_agent = _register_agent(api_client, owner["access_token"])
    their_agent = _register_agent(api_client, other["access_token"])

    with sqlite_session_factory() as db:
        our_post = _seed_post(
            db, organization_id=owner["organization"]["id"], author_agent_id=our_agent["id"]
        )
        # Sent by us: our post → any recipient.
        sent = _seed_delivery(
            db,
            organization_id=owner["organization"]["id"],
            post_id=our_post.id,
            agent_id=our_agent["id"],
            status="delivered",
            delivered_at=datetime.now(UTC),
        )
        # Received by us: another tenant's post → our agent.
        their_post = _seed_post(
            db, organization_id=other["organization"]["id"], author_agent_id=their_agent["id"]
        )
        received = _seed_delivery(
            db,
            organization_id=other["organization"]["id"],
            post_id=their_post.id,
            agent_id=our_agent["id"],
            status="failed",
            attempts=1,
        )
        # Hidden: purely foreign (their post → their agent).
        _seed_delivery(
            db,
            organization_id=other["organization"]["id"],
            post_id=their_post.id,
            agent_id=their_agent["id"],
        )
        sent_id, received_id = str(sent.id), str(received.id)

    response = api_client.get(NOTIFICATIONS, headers=_bearer(owner["access_token"]))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["total"] == 2
    ids = {row["id"] for row in payload["data"]}
    assert ids == {sent_id, received_id}
    # FR-16 outcomes are derived per row.
    by_id = {row["id"]: row for row in payload["data"]}
    assert by_id[sent_id]["outcome"] == "NOTIFIED"
    assert by_id[received_id]["outcome"] == "PENDING"
    assert by_id[sent_id]["status"] == "delivered"
    assert by_id[sent_id]["max_attempts"] >= 1


def test_list_filters_by_status_and_post(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    agent = _register_agent(api_client, owner["access_token"])

    with sqlite_session_factory() as db:
        post_a = _seed_post(
            db, organization_id=owner["organization"]["id"], author_agent_id=agent["id"]
        )
        post_b = _seed_post(
            db, organization_id=owner["organization"]["id"], author_agent_id=agent["id"]
        )
        _seed_delivery(db, organization_id=owner["organization"]["id"], post_id=post_a.id, agent_id=agent["id"])
        dead = _seed_delivery(
            db,
            organization_id=owner["organization"]["id"],
            post_id=post_b.id,
            agent_id=agent["id"],
            status="dead",
            attempts=5,
        )
        post_b_id = str(post_b.id)
        dead_id = str(dead.id)

    headers = _bearer(owner["access_token"])
    dead_rows = api_client.get(f"{NOTIFICATIONS}?status=dead", headers=headers)
    assert dead_rows.status_code == 200
    assert dead_rows.json()["meta"]["total"] == 1
    assert dead_rows.json()["data"][0]["id"] == dead_id

    filtered = api_client.get(f"{NOTIFICATIONS}?post_id={post_b_id}", headers=headers)
    assert filtered.status_code == 200
    assert filtered.json()["meta"]["total"] == 1

    invalid = api_client.get(f"{NOTIFICATIONS}?status=nonsense", headers=headers)
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_detail_hides_cross_tenant_and_never_exposes_the_url(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    other = _register(api_client, email="other@example.test", organization_name="Other")
    our_agent = _register_agent(api_client, owner["access_token"])
    their_agent = _register_agent(api_client, other["access_token"])

    with sqlite_session_factory() as db:
        our_post = _seed_post(
            db, organization_id=owner["organization"]["id"], author_agent_id=our_agent["id"]
        )
        ours = _seed_delivery(
            db,
            organization_id=owner["organization"]["id"],
            post_id=our_post.id,
            agent_id=our_agent["id"],
            status="failed",
            attempts=2,
        )
        their_post = _seed_post(
            db, organization_id=other["organization"]["id"], author_agent_id=their_agent["id"]
        )
        theirs = _seed_delivery(
            db,
            organization_id=other["organization"]["id"],
            post_id=their_post.id,
            agent_id=their_agent["id"],
        )
        ours_id, theirs_id = str(ours.id), str(theirs.id)

    response = api_client.get(
        f"{NOTIFICATIONS}/{ours_id}", headers=_bearer(owner["access_token"])
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["attempts"] == 2
    assert data["response_status"] is None
    # NFR-10: never expose webhook configuration or payloads.
    assert "url" not in data
    assert "payload" not in data
    assert "https://example.com/hook" not in response.text

    cross = api_client.get(
        f"{NOTIFICATIONS}/{theirs_id}", headers=_bearer(owner["access_token"])
    )
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "not_found"

    unknown = api_client.get(f"{NOTIFICATIONS}/{uuid4()}", headers=_bearer(owner["access_token"]))
    assert unknown.status_code == 404


def test_retry_endpoint_resets_failed_delivery(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    agent = _register_agent(api_client, owner["access_token"])

    with sqlite_session_factory() as db:
        post = _seed_post(
            db, organization_id=owner["organization"]["id"], author_agent_id=agent["id"]
        )
        failed = _seed_delivery(
            db,
            organization_id=owner["organization"]["id"],
            post_id=post.id,
            agent_id=agent["id"],
            status="dead",
            attempts=5,
            next_attempt_at=None,
        )
        failed_id, event_id = str(failed.id), str(failed.event_id)

    response = api_client.post(
        f"{NOTIFICATIONS}/{failed_id}/retry", headers=_bearer(owner["access_token"])
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "pending"
    assert data["attempts"] == 0
    assert data["event_id"] == event_id, "receiver idempotency key stays stable"
    assert data["next_attempt_at"] is None


def test_retry_endpoint_rejects_delivered_and_cross_tenant(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    other = _register(api_client, email="other@example.test", organization_name="Other")
    our_agent = _register_agent(api_client, owner["access_token"])
    their_agent = _register_agent(api_client, other["access_token"])

    with sqlite_session_factory() as db:
        our_post = _seed_post(
            db, organization_id=owner["organization"]["id"], author_agent_id=our_agent["id"]
        )
        delivered = _seed_delivery(
            db,
            organization_id=owner["organization"]["id"],
            post_id=our_post.id,
            agent_id=our_agent["id"],
            status="delivered",
            delivered_at=datetime.now(UTC),
        )
        their_post = _seed_post(
            db, organization_id=other["organization"]["id"], author_agent_id=their_agent["id"]
        )
        theirs = _seed_delivery(
            db,
            organization_id=other["organization"]["id"],
            post_id=their_post.id,
            agent_id=their_agent["id"],
            status="failed",
            attempts=1,
        )
        delivered_id, theirs_id = str(delivered.id), str(theirs.id)

    conflict = api_client.post(
        f"{NOTIFICATIONS}/{delivered_id}/retry", headers=_bearer(owner["access_token"])
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "delivery_not_retryable"

    cross = api_client.post(
        f"{NOTIFICATIONS}/{theirs_id}/retry", headers=_bearer(owner["access_token"])
    )
    assert cross.status_code == 404


def test_summary_endpoint_returns_status_and_outcome_totals(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    agent = _register_agent(api_client, owner["access_token"])

    with sqlite_session_factory() as db:
        post = _seed_post(
            db, organization_id=owner["organization"]["id"], author_agent_id=agent["id"]
        )
        _seed_delivery(
            db,
            organization_id=owner["organization"]["id"],
            post_id=post.id,
            agent_id=agent["id"],
            status="dead",
            attempts=5,
        )

    response = api_client.get(
        f"{NOTIFICATIONS}/summary", headers=_bearer(owner["access_token"])
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert set(data["by_status"]) == {"pending", "delivered", "failed", "dead"}
    assert set(data["by_outcome"]) == {"PENDING", "NOTIFIED", "ENGAGED", "IGNORED", "FAILED"}
    assert data["by_status"]["dead"] == 1
    assert data["by_outcome"]["FAILED"] == 1


def test_empty_tenant_gets_zeroed_summary(
    api_client: TestClient,
) -> None:
    owner = _register(api_client, email="fresh@example.test", organization_name="Fresh")
    response = api_client.get(
        f"{NOTIFICATIONS}/summary", headers=_bearer(owner["access_token"])
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert sum(data["by_status"].values()) == 0
    assert sum(data["by_outcome"].values()) == 0


def test_retry_forbidden_for_member_role(
    api_client: TestClient, sqlite_session_factory: sessionmaker[Session]
) -> None:
    owner = _register(api_client, email="owner@example.test", organization_name="Acme")
    agent = _register_agent(api_client, owner["access_token"])
    with sqlite_session_factory() as db:
        post = _seed_post(
            db, organization_id=owner["organization"]["id"], author_agent_id=agent["id"]
        )
        failed = _seed_delivery(
            db,
            organization_id=owner["organization"]["id"],
            post_id=post.id,
            agent_id=agent["id"],
            status="failed",
            attempts=1,
        )
        failed_id = str(failed.id)

    member = _register(api_client, email="member@example.test", organization_name="Member Co")
    api_client.post(
        f"/api/v1/organizations/{owner['organization']['id']}/members",
        json={"email": "member@example.test", "role": "member"},
        headers=_bearer(owner["access_token"]),
    )
    login = api_client.post(
        "/api/v1/auth/login", json={"email": "member@example.test", "password": PASSWORD}
    )
    member_token = login.json()["data"]["access_token"]
    api_client.post(
        "/api/v1/organizations/switch",
        json={"organization_id": owner["organization"]["id"]},
        headers=_bearer(member_token),
    )
    assert member["organization"]["id"] != owner["organization"]["id"]

    # Reads are fine for members; retrying is a management action.
    listed = api_client.get(NOTIFICATIONS, headers=_bearer(member_token))
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1

    forbidden = api_client.post(
        f"{NOTIFICATIONS}/{failed_id}/retry", headers=_bearer(member_token)
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"
