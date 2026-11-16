"""Webhook delivery service (Phase 7): queueing, signed sends, retries.

Lifecycle of one :class:`WebhookDelivery`:

* **queue** — :func:`queue_deliveries` runs inside the routing transaction and
  creates one pending row per selected recipient (FR-10). The row's unique
  ``(post_id, recipient_agent_id)`` constraint makes queueing idempotent
  (FR-12 "avoid duplicate logical notifications"), and the signed payload is
  snapshotted once so only the timestamp header changes between attempts.
* **send** — :func:`deliver` performs exactly one HTTP POST with the four
  plan-mandated headers, an HMAC-SHA256 signature (FR-20) and a strict
  timeout. The URL is re-validated against the SSRF policy immediately before
  every send (DNS rebinding defence).
* **retry** — failures set ``failed`` with an exponential-backoff
  ``next_attempt_at`` (equal jitter, capped); once ``webhook_max_attempts``
  is exhausted the row becomes ``dead`` (FR-12 bounded retries and permanent
  failure records). Every attempt appends a ``webhook_delivery_attempts`` row.
* **sweep** — :func:`sweep_due` finds rows ready for another attempt; Celery
  beat re-enqueues them, so retries survive worker restarts and broker
  outages.

Delivery is at-least-once: a crash after a successful POST but before the
commit redelivers the same event with the same stable ``event_id``, which is
exactly how receivers deduplicate.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.modules.agents.models import Agent
from app.modules.agents.webhook import decrypt_webhook_secret, validate_webhook_url
from app.modules.organizations.models import Organization
from app.modules.posts.models import Post
from app.modules.webhooks.models import (
    DeliveryStatus,
    WebhookDelivery,
    WebhookDeliveryAttempt,
)
from app.modules.webhooks.signing import compute_signature, delivery_headers

logger = logging.getLogger(__name__)

EVENT_TYPE = "post.published"
_RETRYABLE_STATUSES = (DeliveryStatus.PENDING.value, DeliveryStatus.FAILED.value)
_MANUAL_RETRY_STATUSES = (DeliveryStatus.FAILED.value, DeliveryStatus.DEAD.value)


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_error(exc: Exception) -> str:
    """Failure text without secrets, payload content or full URLs."""
    return f"{type(exc).__name__}: {exc}"[:500]


def retry_delay_seconds(attempt: int) -> float:
    """Exponential backoff with equal jitter (FR-12), capped.

    ``delay = min(base * 2**(attempt-1), cap)`` then ``delay/2 + U(0, delay/2)``
    so retries spread out without ever exceeding the cap.
    """
    base = settings.webhook_retry_base_seconds
    cap = settings.webhook_retry_max_seconds
    delay = min(base * (2 ** (attempt - 1)), cap)
    return delay / 2 + random.uniform(0, delay / 2)


# ---------------------------------------------------------------------------
# Queueing (called from inside the routing transaction)
# ---------------------------------------------------------------------------


def build_payload(db: Session, *, post: Post, event_id: UUID) -> dict:
    """FR-11 body: event id, post information, sender information, timestamp."""
    author = db.get(Agent, post.author_agent_id)
    organization = db.get(Organization, post.organization_id)
    published_at = post.published_at or post.created_at
    return {
        "event_id": str(event_id),
        "event_type": EVENT_TYPE,
        "timestamp": published_at.isoformat(),
        "data": {
            "post": {
                "id": str(post.id),
                "title": post.title,
                "content": post.content,
                "published_at": published_at.isoformat(),
            },
            "sender": {
                "agent_id": str(post.author_agent_id),
                "agent_name": author.company_name if author else None,
                "organization_id": str(post.organization_id),
                "organization_name": organization.name if organization else None,
            },
        },
    }


def queue_deliveries(
    db: Session, *, post: Post, recipient_ids: list[UUID]
) -> list[WebhookDelivery]:
    """Stage one pending delivery per selected recipient (FR-10).

    Runs in the caller's transaction (the routing write), so routing decisions
    and their deliveries commit or roll back together. The recipient agent's
    webhook URL is snapshotted after an SSRF policy check; agents without a
    configured webhook are skipped (they simply receive no notification).
    """
    deliveries: list[WebhookDelivery] = []
    seen: set[UUID] = set()
    for agent_id in recipient_ids:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        agent = db.get(Agent, agent_id)
        if agent is None or not agent.webhook_url:
            continue
        try:
            url = validate_webhook_url(agent.webhook_url)
        except AppError:
            logger.warning(
                "Skipping webhook delivery: URL fails SSRF policy",
                extra={"agent_id": str(agent_id)},
            )
            continue
        event_id = uuid4()
        deliveries.append(
            WebhookDelivery(
                event_id=event_id,
                organization_id=post.organization_id,
                post_id=post.id,
                recipient_agent_id=agent_id,
                event_type=EVENT_TYPE,
                payload=build_payload(db, post=post, event_id=event_id),
                url=url,
                status=DeliveryStatus.PENDING.value,
            )
        )
    db.add_all(deliveries)
    return deliveries


def void_post_deliveries(db: Session, *, post_id: UUID) -> None:
    """Drop a post's delivery records when a re-edit voids its routing run.

    Mirrors the routing-log voiding decision: stale-content notifications must
    not survive to block or contradict the fresh routing after re-publish.
    (Webhooks already sent cannot be unsent; their history rows are removed
    with the void, documented in the phase report.)
    """
    db.execute(WebhookDelivery.__table__.delete().where(WebhookDelivery.post_id == post_id))


# ---------------------------------------------------------------------------
# One delivery attempt
# ---------------------------------------------------------------------------


def _send(url: str, body: bytes, headers: dict[str, str]) -> httpx.Response:
    """HTTP POST with a strict timeout and no redirect following."""
    return httpx.post(
        url,
        content=body,
        headers=headers,
        timeout=settings.webhook_timeout_seconds,
        follow_redirects=False,
    )


def deliver(db: Session, *, delivery_id: UUID) -> str:
    """Execute exactly one delivery attempt. Returns an outcome code.

    Outcomes: ``not_found``, ``already_delivered``, ``delivered``,
    ``failed`` (retry scheduled), ``dead`` (bounded retries exhausted).
    """
    # Lock the row for the attempt: two concurrent task deliveries of the same
    # id serialize here, so attempt numbers never double-count (the unique
    # (delivery_id, attempt_number) constraint is the backstop). SQLite
    # ignores FOR UPDATE; PostgreSQL enforces it.
    delivery = db.scalar(
        select(WebhookDelivery)
        .where(WebhookDelivery.id == delivery_id)
        .with_for_update()
    )
    if delivery is None:
        return "not_found"
    if delivery.status == DeliveryStatus.DELIVERED.value:
        return "already_delivered"
    if delivery.status == DeliveryStatus.DEAD.value:
        # Dead rows only move again through the manual retry API, which
        # resets them to pending with a fresh bounded cycle first.
        return "dead"

    attempt_number = delivery.attempts + 1
    now = _now()
    response_status: int | None = None
    error: str | None = None

    try:
        # SSRF re-validation at send time: the policy is re-checked against
        # the current DNS/IP state, not just the queue-time snapshot.
        validate_webhook_url(delivery.url)
        agent = db.get(Agent, delivery.recipient_agent_id)
        if agent is None or not agent.webhook_secret_encrypted:
            raise AppError(
                "Recipient webhook is not configured.",
                code="webhook_not_configured",
                status_code=409,
            )
        secret = decrypt_webhook_secret(agent.webhook_secret_encrypted)
        body = json.dumps(delivery.payload, sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(now.timestamp()))
        headers = delivery_headers(
            event_id=str(delivery.event_id),
            event_type=delivery.event_type,
            timestamp=timestamp,
            signature=compute_signature(secret, timestamp=timestamp, body=body),
        )
        response = _send(delivery.url, body, headers)
        response_status = response.status_code
        if not 200 <= response_status < 300:
            error = f"http_{response_status}"
    except Exception as exc:  # noqa: BLE001 - any transport/policy error fails the attempt
        error = _safe_error(exc)

    # FR-12: record every attempt, then update the delivery's lifecycle.
    db.add(
        WebhookDeliveryAttempt(
            delivery_id=delivery.id,
            attempt_number=attempt_number,
            response_status=response_status,
            error=error,
        )
    )
    delivery.attempts = attempt_number
    delivery.last_attempt_at = now
    delivery.response_status = response_status

    if error is None:
        delivery.status = DeliveryStatus.DELIVERED.value
        delivery.delivered_at = now
        delivery.next_attempt_at = None
        delivery.last_error = None
    else:
        delivery.last_error = error[:500]
        if attempt_number >= settings.webhook_max_attempts:
            delivery.status = DeliveryStatus.DEAD.value
            delivery.next_attempt_at = None
            logger.warning(
                "Webhook delivery dead-lettered",
                extra={
                    "delivery_id": str(delivery.id),
                    "attempts": attempt_number,
                },
            )
        else:
            delivery.status = DeliveryStatus.FAILED.value
            delivery.next_attempt_at = now + timedelta(seconds=retry_delay_seconds(attempt_number))
    db.commit()
    return delivery.status


# ---------------------------------------------------------------------------
# Sweeper and manual retry
# ---------------------------------------------------------------------------


def sweep_due(db: Session, *, limit: int | None = None) -> list[UUID]:
    """Delivery ids ready for another attempt (due pending/failed rows)."""
    now = _now()
    statement = (
        select(WebhookDelivery.id)
        .where(
            WebhookDelivery.status.in_(_RETRYABLE_STATUSES),
            or_(
                WebhookDelivery.next_attempt_at.is_(None),
                WebhookDelivery.next_attempt_at <= now,
            ),
        )
        .order_by(WebhookDelivery.next_attempt_at.nullsfirst(), WebhookDelivery.created_at)
        .limit(limit or settings.webhook_sweep_batch)
    )
    return list(db.scalars(statement).all())


def enqueue_delivery(delivery_id: UUID) -> None:
    """Best-effort task enqueue; the beat sweeper recovers anything missed."""
    from app.workers.webhook_tasks import deliver as deliver_task

    try:
        deliver_task.delay(str(delivery_id))
    except Exception:  # noqa: BLE001 - the delivery row persists regardless
        logger.warning(
            "Webhook enqueue failed; sweep will retry",
            extra={"delivery_id": str(delivery_id)},
        )


def retry_delivery(db: Session, *, delivery_id: UUID, organization_id: UUID) -> WebhookDelivery:
    """Manually re-open a failed/dead delivery with a fresh retry cycle.

    Resets the bounded-retry counter (a human explicitly asked for a new
    cycle) while keeping the stable ``event_id`` and the full attempt history,
    so receivers still see one logical notification.
    """
    delivery = get_visible_delivery(db, delivery_id=delivery_id, organization_id=organization_id)
    if delivery.status not in _MANUAL_RETRY_STATUSES:
        raise AppError(
            "Only failed or dead deliveries can be retried.",
            code="delivery_not_retryable",
            status_code=409,
        )
    delivery.status = DeliveryStatus.PENDING.value
    delivery.attempts = 0
    delivery.next_attempt_at = None
    db.commit()
    db.refresh(delivery)
    enqueue_delivery(delivery.id)
    return delivery


# ---------------------------------------------------------------------------
# Tenant-scoped reads
# ---------------------------------------------------------------------------


def _visibility_statement(organization_id: UUID):
    """Deliveries this tenant may see: sent by our posts or received by our agents."""
    return or_(
        WebhookDelivery.organization_id == organization_id,
        WebhookDelivery.recipient_agent_id.in_(
            select(Agent.id).where(Agent.organization_id == organization_id)
        ),
    )


def get_visible_delivery(
    db: Session, *, delivery_id: UUID, organization_id: UUID
) -> WebhookDelivery:
    delivery = db.scalar(
        select(WebhookDelivery).where(
            WebhookDelivery.id == delivery_id,
            _visibility_statement(organization_id),
        )
    )
    if delivery is None:
        raise AppError("Notification not found.", code="not_found", status_code=404)
    return delivery


def list_deliveries(
    db: Session,
    *,
    organization_id: UUID,
    status: str | None,
    post_id: UUID | None,
    page: int,
    page_size: int,
) -> tuple[list[WebhookDelivery], int]:
    predicates = [_visibility_statement(organization_id)]
    if status is not None:
        predicates.append(WebhookDelivery.status == status)
    if post_id is not None:
        predicates.append(WebhookDelivery.post_id == post_id)
    total = db.scalar(select(func.count()).select_from(WebhookDelivery).where(*predicates)) or 0
    deliveries = list(
        db.scalars(
            select(WebhookDelivery)
            .where(*predicates)
            .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return deliveries, total


def engagement_outcomes(db: Session, deliveries: list[WebhookDelivery]) -> dict[UUID, str]:
    """FR-16 outcomes derived from delivery state and recipient responses.

    ``PENDING`` (not yet delivered), ``NOTIFIED`` (delivered, waiting),
    ``ENGAGED`` (recipient commented on the post after delivery), ``IGNORED``
    (delivered, no comment within ``engagement_window_days``) and ``FAILED``
    (dead-lettered). Computed on read — no background state machine, and it
    stays correct as new comments arrive.
    """
    outcomes: dict[UUID, str] = {}
    delivered = [d for d in deliveries if d.status == DeliveryStatus.DELIVERED.value]
    comments: set[tuple[UUID, UUID, datetime]] = set()
    if delivered:
        from app.modules.comments.models import Comment

        pairs = {(d.post_id, d.recipient_agent_id) for d in delivered}
        rows = db.execute(
            select(Comment.post_id, Comment.author_agent_id, Comment.created_at).where(
                Comment.post_id.in_({p for p, _ in pairs}),
                Comment.author_agent_id.in_({a for _, a in pairs}),
            )
        ).all()
        comments = {(row[0], row[1], row[2]) for row in rows}

    window = timedelta(days=settings.engagement_window_days)
    now = _now()
    for delivery in deliveries:
        if delivery.status == DeliveryStatus.DEAD.value:
            outcomes[delivery.id] = "FAILED"
        elif delivery.status != DeliveryStatus.DELIVERED.value:
            outcomes[delivery.id] = "PENDING"
        elif delivery.delivered_at is None:
            outcomes[delivery.id] = "NOTIFIED"
        elif any(
            post_id == delivery.post_id
            and agent_id == delivery.recipient_agent_id
            and created_at >= delivery.delivered_at
            for post_id, agent_id, created_at in comments
        ):
            outcomes[delivery.id] = "ENGAGED"
        elif now > delivery.delivered_at + window:
            outcomes[delivery.id] = "IGNORED"
        else:
            outcomes[delivery.id] = "NOTIFIED"
    return outcomes


def delivery_summary(db: Session, *, organization_id: UUID) -> dict[str, dict[str, int]]:
    """Delivery-status totals plus FR-16 outcome totals for the tenant.

    Outcomes are aggregated with SQL (correlated comment existence) so the
    summary stays correct at any volume — same precedence as
    :func:`engagement_outcomes`: engaged beats ignored beats notified.
    """
    from app.modules.comments.models import Comment

    visible = _visibility_statement(organization_id)
    status_rows = db.execute(
        select(WebhookDelivery.status, func.count()).where(visible).group_by(WebhookDelivery.status)
    ).all()
    by_status = {status.value: 0 for status in DeliveryStatus}
    by_status.update({row[0]: row[1] for row in status_rows})

    comment_exists = (
        select(Comment.id)
        .where(
            Comment.post_id == WebhookDelivery.post_id,
            Comment.author_agent_id == WebhookDelivery.recipient_agent_id,
            Comment.created_at >= WebhookDelivery.delivered_at,
        )
        .exists()
    )
    delivered_predicate = (
        visible,
        WebhookDelivery.status == DeliveryStatus.DELIVERED.value,
    )
    engaged = (
        db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(*delivered_predicate, comment_exists)
        )
        or 0
    )
    cutoff = _now() - timedelta(days=settings.engagement_window_days)
    ignored = (
        db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(
                *delivered_predicate,
                WebhookDelivery.delivered_at < cutoff,
                ~comment_exists,
            )
        )
        or 0
    )
    delivered_total = by_status[DeliveryStatus.DELIVERED.value]
    by_outcome = {
        "PENDING": by_status[DeliveryStatus.PENDING.value] + by_status[DeliveryStatus.FAILED.value],
        "NOTIFIED": max(delivered_total - engaged - ignored, 0),
        "ENGAGED": engaged,
        "IGNORED": ignored,
        "FAILED": by_status[DeliveryStatus.DEAD.value],
    }
    return {"by_status": by_status, "by_outcome": by_outcome}
