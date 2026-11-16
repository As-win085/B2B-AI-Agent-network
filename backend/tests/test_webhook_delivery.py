"""Webhook delivery service: queueing, signed sends, retries and recovery.

HTTP is always mocked (``_send``) and DNS resolution is patched, so these
tests never touch the network. Covering FR-10 through FR-12, FR-16 and FR-20.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.modules.agents.models import Agent, AgentStatus
from app.modules.agents.service import register_agent
from app.modules.agents.webhook import encrypt_webhook_secret
from app.modules.organizations.models import Organization
from app.modules.posts.models import Post, PostStatus
from app.modules.webhooks import service
from app.modules.webhooks.models import (
    DeliveryStatus,
    WebhookDelivery,
    WebhookDeliveryAttempt,
)
from app.modules.webhooks.signing import (
    EVENT_ID_HEADER,
    EVENT_TYPE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    verify_signature,
)
from tests.test_routing_service import HIGH_A, IDENTICAL, POST_VECTOR, _version

_WEBHOOK_URL = "https://example.com/hook"
_SECRET = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"


@contextmanager
def _dns_public():
    """SSRF validation resolves the hostname to a public address."""
    with patch(
        "app.modules.agents.webhook.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
    ):
        yield


@contextmanager
def _dns_metadata():
    """SSRF validation resolves the hostname to a blocked link-local address."""
    with patch(
        "app.modules.agents.webhook.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("169.254.169.254", 80))],
    ):
        yield


def _organization(db: Session) -> Organization:
    org = Organization(name="Hook Corp", slug=f"hook-{uuid4().hex[:8]}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _agent(db: Session, org: Organization, *, name: str) -> Agent:
    agent = register_agent(
        db,
        organization_id=org.id,
        company_name=name,
        industry_category=None,
        interest_manifesto="interests",
    )
    return agent


def _configure(agent: Agent, db: Session, *, url: str = _WEBHOOK_URL) -> None:
    agent.webhook_url = url
    agent.webhook_secret_encrypted = encrypt_webhook_secret(_SECRET)
    db.commit()


def _published_post(db: Session, org: Organization, author: Agent) -> Post:
    now = datetime.now(UTC)
    post = Post(
        organization_id=org.id,
        author_agent_id=author.id,
        title="Webhook post",
        content="Content that triggers notifications.",
        status=PostStatus.PUBLISHED.value,
        embedding=POST_VECTOR,
        embedding_provider="openai",
        embedding_model="test-model",
        embedding_generation=1,
        published_at=now,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def _delivery_for(db: Session, post: Post, recipient: Agent) -> WebhookDelivery:
    deliveries = service.queue_deliveries(db, post=post, recipient_ids=[recipient.id])
    db.commit()
    assert len(deliveries) == 1
    db.refresh(deliveries[0])
    return deliveries[0]


def _attempt_count(db: Session, delivery_id) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(WebhookDeliveryAttempt)
            .where(WebhookDeliveryAttempt.delivery_id == delivery_id)
        )
        or 0
    )


def _reload(db: Session, delivery_id) -> WebhookDelivery:
    db.expire_all()
    delivery = db.scalar(
        select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
    )
    assert delivery is not None
    return delivery


class _FakeSend:
    """Stands in for the HTTP POST; records the exact request."""

    def __init__(self, *, status_code: int = 200, error: Exception | None = None) -> None:
        self.status_code = status_code
        self.error = error
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]):
        self.calls.append((url, body, dict(headers)))
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status_code)


# ---------------------------------------------------------------------------
# FR-10: queueing
# ---------------------------------------------------------------------------


def test_queue_creates_pending_record_with_fr11_payload(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)

    with _dns_public():
        [delivery] = service.queue_deliveries(db, post=post, recipient_ids=[recipient.id])
    db.commit()

    assert delivery.status == DeliveryStatus.PENDING.value
    assert delivery.attempts == 0
    assert delivery.url == _WEBHOOK_URL
    assert delivery.organization_id == org.id
    assert delivery.event_type == "post.published"
    # FR-11 payload: event id, timestamp, post and sender information.
    payload = delivery.payload
    assert payload["event_id"] == str(delivery.event_id)
    assert payload["event_type"] == "post.published"
    assert payload["timestamp"] == post.published_at.isoformat()
    assert payload["data"]["post"]["id"] == str(post.id)
    assert payload["data"]["post"]["title"] == post.title
    assert payload["data"]["post"]["content"] == post.content
    assert payload["data"]["sender"]["agent_id"] == str(author.id)
    assert payload["data"]["sender"]["organization_id"] == str(org.id)
    assert payload["data"]["sender"]["organization_name"] == org.name


def test_queue_skips_agents_without_webhook_or_with_blocked_url(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    unconfigured = _agent(db, org, name="Unconfigured")
    blocked = _agent(db, org, name="Blocked")
    blocked.webhook_url = "http://169.254.169.254/latest/meta-data/"  # scheme blocked
    db.commit()
    post = _published_post(db, org, author)

    deliveries = service.queue_deliveries(
        db, post=post, recipient_ids=[unconfigured.id, blocked.id]
    )
    assert deliveries == []


def test_queue_is_idempotent_per_post_and_recipient(db: Session) -> None:
    """FR-12: duplicate routing runs can never create a second notification."""
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)

    with _dns_public():
        service.queue_deliveries(db, post=post, recipient_ids=[recipient.id])
        db.commit()
        service.queue_deliveries(db, post=post, recipient_ids=[recipient.id])
        with pytest.raises(Exception) as excinfo:
            db.commit()
    assert "unique" in str(excinfo.value).lower()
    db.rollback()


def test_post_re_edit_voids_stale_deliveries(db: Session) -> None:
    from app.modules.posts import service as posts_service

    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    _delivery_for(db, post, recipient)

    _, text_changed = posts_service.update_post_by_author(
        db, post_id=post.id, agent=author, fields={"title": "Edited title"}
    )

    assert text_changed is True
    remaining = db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.post_id == post.id)
    )
    assert remaining == 0


# ---------------------------------------------------------------------------
# FR-11/FR-20: signed delivery
# ---------------------------------------------------------------------------


def test_successful_delivery_sends_signed_headers_and_records_attempt(
    db: Session,
) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    sender = _FakeSend(status_code=204)

    with _dns_public():
        with patch("app.modules.webhooks.service._send", sender):
            outcome = service.deliver(db, delivery_id=delivery.id)

    assert outcome == "delivered"
    loaded = _reload(db, delivery.id)
    assert loaded.status == DeliveryStatus.DELIVERED.value
    assert loaded.attempts == 1
    assert loaded.response_status == 204
    assert loaded.delivered_at is not None
    assert loaded.last_error is None
    assert _attempt_count(db, delivery.id) == 1

    url, body, headers = sender.calls[0]
    assert url == _WEBHOOK_URL
    # Exactly the four plan-mandated headers.
    assert set(headers) == {
        EVENT_ID_HEADER,
        EVENT_TYPE_HEADER,
        TIMESTAMP_HEADER,
        SIGNATURE_HEADER,
    }
    assert headers[EVENT_ID_HEADER] == str(delivery.event_id)
    assert headers[EVENT_TYPE_HEADER] == "post.published"
    # The receiver can verify the signature with the shared secret (FR-20).
    assert verify_signature(
        _SECRET,
        timestamp=headers[TIMESTAMP_HEADER],
        body=body,
        signature=headers[SIGNATURE_HEADER],
    )
    # Body is the snapshotted payload — stable across retries.
    assert json.loads(body) == delivery.payload


def test_delivered_delivery_is_idempotent(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    sender = _FakeSend()

    with _dns_public():
        with patch("app.modules.webhooks.service._send", sender):
            assert service.deliver(db, delivery_id=delivery.id) == "delivered"
            assert service.deliver(db, delivery_id=delivery.id) == "already_delivered"

    assert len(sender.calls) == 1
    assert _attempt_count(db, delivery.id) == 1


def test_payload_signature_changes_per_attempt_but_event_id_does_not(
    db: Session,
) -> None:
    """Retries keep one logical identity (dedupe key) while remaining fresh."""
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    failing = _FakeSend(status_code=500)

    with _dns_public():
        with patch("app.modules.webhooks.service._send", failing):
            assert service.deliver(db, delivery_id=delivery.id) == "failed"
            assert service.deliver(db, delivery_id=delivery.id) == "failed"

    first, second = failing.calls
    assert first[1] == second[1], "body must be byte-identical across attempts"
    assert (
        first[2][EVENT_ID_HEADER] == second[2][EVENT_ID_HEADER]
    ), "event id is the receiver idempotency key"
    assert (
        first[2][SIGNATURE_HEADER] != second[2][SIGNATURE_HEADER]
    ), "each attempt is signed with its own timestamp"


# ---------------------------------------------------------------------------
# FR-12: retries, backoff, dead-lettering
# ---------------------------------------------------------------------------


def test_non_2xx_response_records_attempt_and_schedules_backoff(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    failing = _FakeSend(status_code=503)

    with _dns_public():
        with patch("app.modules.webhooks.service._send", failing):
            outcome = service.deliver(db, delivery_id=delivery.id)

    assert outcome == "failed"
    loaded = _reload(db, delivery.id)
    assert loaded.status == DeliveryStatus.FAILED.value
    assert loaded.attempts == 1
    assert loaded.response_status == 503
    assert loaded.last_error == "http_503"
    assert loaded.next_attempt_at is not None
    now = datetime.now(UTC)
    lower = now + timedelta(seconds=settings.webhook_retry_base_seconds / 2)
    upper = now + timedelta(seconds=settings.webhook_retry_base_seconds)
    assert lower - timedelta(seconds=5) <= loaded.next_attempt_at <= upper + timedelta(
        seconds=5
    )
    [attempt] = [
        a
        for a in db.scalars(
            select(WebhookDeliveryAttempt).where(
                WebhookDeliveryAttempt.delivery_id == delivery.id
            )
        )
    ]
    assert attempt.attempt_number == 1
    assert attempt.response_status == 503
    assert attempt.error == "http_503"


def test_transport_timeout_is_recorded_as_failed_attempt(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    failing = _FakeSend(error=httpx.ConnectTimeout("timed out"))

    with _dns_public():
        with patch("app.modules.webhooks.service._send", failing):
            outcome = service.deliver(db, delivery_id=delivery.id)

    assert outcome == "failed"
    loaded = _reload(db, delivery.id)
    assert "Timeout" in (loaded.last_error or "")
    assert loaded.response_status is None
    assert _attempt_count(db, delivery.id) == 1


def test_dead_letter_after_bounded_retries(db: Session, monkeypatch) -> None:
    """FR-12: bounded retries, permanent failures recorded, no endless loop."""
    monkeypatch.setattr(settings, "webhook_max_attempts", 2)
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    failing = _FakeSend(status_code=500)

    with _dns_public():
        with patch("app.modules.webhooks.service._send", failing):
            assert service.deliver(db, delivery_id=delivery.id) == "failed"
            assert service.deliver(db, delivery_id=delivery.id) == "dead"
            # Dead rows are inert until the manual retry API re-opens them.
            assert service.deliver(db, delivery_id=delivery.id) == "dead"

    loaded = _reload(db, delivery.id)
    assert loaded.status == DeliveryStatus.DEAD.value
    assert loaded.attempts == 2
    assert loaded.next_attempt_at is None
    assert _attempt_count(db, delivery.id) == 2
    assert len(failing.calls) == 2


def test_backoff_is_exponential_with_jitter_and_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "webhook_retry_base_seconds", 4.0)
    monkeypatch.setattr(settings, "webhook_retry_max_seconds", 10.0)
    for _ in range(50):
        first = service.retry_delay_seconds(1)
        second = service.retry_delay_seconds(2)
        third = service.retry_delay_seconds(3)
        capped = service.retry_delay_seconds(8)
        assert 2.0 <= first <= 4.0
        assert 4.0 <= second <= 8.0
        assert 8.0 <= third <= 16.0
        assert 5.0 <= capped <= 10.0, "cap must bound the delay"
        assert second >= first * 0.5, "growth is exponential modulo jitter"
    # Jitter actually varies.
    samples = {service.retry_delay_seconds(3) for _ in range(20)}
    assert len(samples) > 1


def test_ssrf_policy_revalidated_at_send_time(db: Session) -> None:
    """DNS rebinding: the URL is checked again immediately before the POST."""
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    sender = _FakeSend()

    with _dns_metadata():  # same hostname now resolves to a blocked address
        with patch("app.modules.webhooks.service._send", sender):
            outcome = service.deliver(db, delivery_id=delivery.id)

    assert outcome == "failed"
    assert sender.calls == [], "no request may leave for a blocked address"
    loaded = _reload(db, delivery.id)
    assert "ssrf_blocked" in (loaded.last_error or "")


def test_missing_signing_secret_fails_the_attempt(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    recipient.webhook_secret_encrypted = None
    db.commit()
    sender = _FakeSend()

    with _dns_public():
        with patch("app.modules.webhooks.service._send", sender):
            outcome = service.deliver(db, delivery_id=delivery.id)

    assert outcome == "failed"
    assert sender.calls == []
    assert "not configured" in (_reload(db, delivery.id).last_error or "")


# ---------------------------------------------------------------------------
# Recovery: sweep and manual retry
# ---------------------------------------------------------------------------


def _raw_delivery(
    db: Session,
    *,
    org_id,
    post_id,
    agent_id,
    status: str,
    next_attempt_at=None,
    attempts: int = 0,
) -> WebhookDelivery:
    delivery = WebhookDelivery(
        event_id=uuid4(),
        organization_id=org_id,
        post_id=post_id,
        recipient_agent_id=agent_id,
        event_type="post.published",
        payload={"event_id": str(uuid4()), "data": {}},
        url=_WEBHOOK_URL,
        status=status,
        attempts=attempts,
        next_attempt_at=next_attempt_at,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def test_sweep_selects_only_due_retryable_deliveries(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    post = _published_post(db, org, author)

    # One delivery per (post, recipient) — the table's uniqueness rule.
    due_agent = _agent(db, org, name="Due")
    future_agent = _agent(db, org, name="Future")
    retryable_agent = _agent(db, org, name="Retryable")
    delivered_agent = _agent(db, org, name="Delivered")
    dead_agent = _agent(db, org, name="Dead")

    due = _raw_delivery(db, org_id=org.id, post_id=post.id, agent_id=due_agent.id, status="pending")
    future = _raw_delivery(
        db,
        org_id=org.id,
        post_id=post.id,
        agent_id=future_agent.id,
        status="failed",
        next_attempt_at=datetime.now(UTC) + timedelta(hours=1),
        attempts=1,
    )
    retryable = _raw_delivery(
        db,
        org_id=org.id,
        post_id=post.id,
        agent_id=retryable_agent.id,
        status="failed",
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        attempts=1,
    )
    delivered = _raw_delivery(
        db, org_id=org.id, post_id=post.id, agent_id=delivered_agent.id, status="delivered"
    )
    dead = _raw_delivery(
        db, org_id=org.id, post_id=post.id, agent_id=dead_agent.id, status="dead", attempts=5
    )

    due_ids = service.sweep_due(db)

    assert set(due_ids) == {due.id, retryable.id}
    assert future.id not in due_ids
    assert delivered.id not in due_ids
    assert dead.id not in due_ids


def test_manual_retry_resets_bounded_cycle_and_re_enqueues(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivery = _delivery_for(db, post, recipient)
    delivery.status = DeliveryStatus.DEAD.value
    delivery.attempts = settings.webhook_max_attempts
    db.commit()

    with patch("app.modules.webhooks.service.enqueue_delivery") as enqueue:
        retried = service.retry_delivery(
            db, delivery_id=delivery.id, organization_id=org.id
        )

    assert retried.status == DeliveryStatus.PENDING.value
    assert retried.attempts == 0
    assert retried.next_attempt_at is None
    assert retried.event_id == delivery.event_id, "identity stays stable for receivers"
    enqueue.assert_called_once_with(delivery.id)


def test_manual_retry_rejects_delivered_and_cross_tenant(db: Session) -> None:
    org = _organization(db)
    other_org = Organization(name="Other", slug=f"other-{uuid4().hex[:8]}")
    db.add(other_org)
    db.commit()
    author = _agent(db, org, name="Author")
    recipient = _agent(db, org, name="Recipient")
    _configure(recipient, db)
    post = _published_post(db, org, author)
    delivered = _delivery_for(db, post, recipient)
    delivered.status = DeliveryStatus.DELIVERED.value
    delivered.delivered_at = datetime.now(UTC)
    db.commit()

    with pytest.raises(AppError) as excinfo:
        service.retry_delivery(db, delivery_id=delivered.id, organization_id=org.id)
    assert excinfo.value.code == "delivery_not_retryable"
    assert excinfo.value.status_code == 409

    with pytest.raises(AppError) as cross:
        service.retry_delivery(
            db, delivery_id=delivered.id, organization_id=other_org.id
        )
    assert cross.value.status_code == 404


# ---------------------------------------------------------------------------
# FR-16: engagement outcomes
# ---------------------------------------------------------------------------


def test_engagement_outcomes_cover_fr16_statuses(db: Session) -> None:
    from app.modules.comments.models import Comment

    org = _organization(db)
    author = _agent(db, org, name="Author")
    post = _published_post(db, org, author)

    # One delivery per (post, recipient): five distinct recipients here.
    pending_agent = _agent(db, org, name="P")
    dead_agent = _agent(db, org, name="D")
    notified_agent = _agent(db, org, name="N")
    engaged_agent = _agent(db, org, name="E")
    ignored_agent = _agent(db, org, name="I")

    pending = _raw_delivery(db, org_id=org.id, post_id=post.id, agent_id=pending_agent.id, status="pending")
    dead = _raw_delivery(db, org_id=org.id, post_id=post.id, agent_id=dead_agent.id, status="dead", attempts=5)

    notified = _raw_delivery(
        db, org_id=org.id, post_id=post.id, agent_id=notified_agent.id, status="delivered"
    )
    notified.delivered_at = datetime.now(UTC)
    db.commit()

    engaged = _raw_delivery(
        db, org_id=org.id, post_id=post.id, agent_id=engaged_agent.id, status="delivered"
    )
    engaged.delivered_at = datetime.now(UTC) - timedelta(days=1)
    db.add(
        Comment(
            organization_id=org.id,
            post_id=post.id,
            author_agent_id=engaged_agent.id,
            content="Interested — let's talk.",
        )
    )
    db.commit()

    ignored = _raw_delivery(
        db, org_id=org.id, post_id=post.id, agent_id=ignored_agent.id, status="delivered"
    )
    ignored.delivered_at = datetime.now(UTC) - timedelta(
        days=settings.engagement_window_days + 1
    )
    db.commit()

    outcomes = service.engagement_outcomes(db, [pending, dead, notified, engaged, ignored])

    assert outcomes[pending.id] == "PENDING"
    assert outcomes[dead.id] == "FAILED"
    assert outcomes[notified.id] == "NOTIFIED"
    assert outcomes[engaged.id] == "ENGAGED"
    assert outcomes[ignored.id] == "IGNORED"


def test_delivery_summary_aggregates_status_and_outcome(db: Session) -> None:
    org = _organization(db)
    author = _agent(db, org, name="Author")
    post = _published_post(db, org, author)
    pending_agent = _agent(db, org, name="P")
    dead_agent = _agent(db, org, name="D")
    done_agent = _agent(db, org, name="N")

    _raw_delivery(db, org_id=org.id, post_id=post.id, agent_id=pending_agent.id, status="pending")
    _raw_delivery(db, org_id=org.id, post_id=post.id, agent_id=dead_agent.id, status="dead", attempts=5)
    delivered = _raw_delivery(
        db, org_id=org.id, post_id=post.id, agent_id=done_agent.id, status="delivered"
    )
    delivered.delivered_at = datetime.now(UTC)
    db.commit()

    summary = service.delivery_summary(db, organization_id=org.id)

    assert summary["by_status"]["pending"] == 1
    assert summary["by_status"]["dead"] == 1
    assert summary["by_status"]["delivered"] == 1
    assert summary["by_outcome"]["PENDING"] == 1
    assert summary["by_outcome"]["FAILED"] == 1
    assert summary["by_outcome"]["NOTIFIED"] == 1
    assert summary["by_outcome"]["ENGAGED"] == 0


# ---------------------------------------------------------------------------
# Bridge: routing results → webhook deliveries
# ---------------------------------------------------------------------------


def test_route_post_queues_deliveries_for_selected_recipients(db: Session) -> None:
    """Phase 7 bridge: selected recipients get a delivery record per run."""
    from app.modules.routing import service as routing_service

    org_a = Organization(name="Org A", slug=f"a-{uuid4().hex[:8]}")
    org_b = Organization(name="Org B", slug=f"b-{uuid4().hex[:8]}")
    db.add_all([org_a, org_b])
    db.commit()

    publisher = _agent(db, org_a, name="Publisher")
    selected = _agent(db, org_a, name="Selected")
    unconfigured = _agent(db, org_a, name="Unconfigured")
    external = _agent(db, org_b, name="External")
    for agent in (selected, unconfigured):
        agent.status = AgentStatus.ACTIVE.value
    db.commit()

    _version(db, publisher, IDENTICAL)
    _version(db, selected, HIGH_A)
    _version(db, unconfigured, HIGH_A)
    post = _published_post(db, org_a, publisher)
    _configure(selected, db)  # only this recipient has a webhook

    with _dns_public():
        outcome = routing_service.route_post(db, post_id=post.id)

    assert outcome.routed is True
    assert outcome.selected >= 1
    deliveries = list(
        db.scalars(
            select(WebhookDelivery).where(WebhookDelivery.post_id == post.id)
        ).all()
    )
    assert [d.recipient_agent_id for d in deliveries] == [selected.id]
    assert deliveries[0].status == DeliveryStatus.PENDING.value
    assert deliveries[0].organization_id == org_a.id
    assert unconfigured.id not in {d.recipient_agent_id for d in deliveries}

    # A duplicate routing run must not duplicate notifications (FR-12).
    with _dns_public():
        second = routing_service.route_post(db, post_id=post.id)
    assert second.reason == "already_routed"
    count = db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.post_id == post.id)
    )
    assert count == 1
