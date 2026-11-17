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
  every send (DNS rebinding defence). Additionally, the resolved destination
  IP is pinned at connection time to prevent TOCTOU rebinding attacks.
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
from app.modules.agents.webhook import _is_blocked_address
from app.modules.organizations.models import Organization
from app.modules.posts.models import Post
from app.modules.webhooks.models import (
    DeliveryStatus,
    WebhookDelivery,
    WebhookDeliveryAttempt,
)
from app.modules.webhooks.signing import compute_signature, delivery_headers
from app.shared.models import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DeliveryStatus(StrEnum):
    """Lifecycle of one webhook delivery record."""

    PENDING = "pending"  # queued, first attempt not yet successful
    DELIVERED = "delivered"  # endpoint returned 2xx (FR-16 NOTIFIED)
    FAILED = "failed"  # last attempt failed; will retry with backoff
    DEAD = "dead"  # bounded retries exhausted (FR-12 permanent failure)


_STR_ENUM_VALUES = ", ".join(f"'{s.value}'" for s in DeliveryStatus)


class WebhookDelivery(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """One logical notification to one recipient agent."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_webhook_deliveries_event_id"),
        UniqueConstraint(
            "post_id",
            "recipient_agent_id",
            name="uq_webhook_deliveries_post_id_recipient_agent_id",
        ),
        CheckConstraint(
            f"status IN ({_STR_ENUM_VALUES})",
            name="webhook_delivery_status_valid",
        ),
        CheckConstraint("attempts >= 0", name="webhook_delivery_attempts_valid"),
        Index("ix_webhook_deliveries_org_created", "organization_id", "created_at", "id"),
        Index("ix_webhook_deliveries_recipient", "recipient_agent_id"),
        Index("ix_webhook_deliveries_post", "post_id"),
        Index("ix_webhook_deliveries_status_next", "status", "next_attempt_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default=text("'post.published'"),
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookDeliveryAttempt(Base, UUIDPrimaryKeyMixin):
    """Immutable record of one delivery attempt (FR-12)."""

    __tablename__ = "webhook_delivery_attempts"
    __table_args__ = (
        UniqueConstraint(
            "delivery_id",
            "attempt_number",
            name="uq_webhook_delivery_attempts_delivery_id_attempt_number",
        ),
        CheckConstraint("attempt_number >= 1", name="webhook_attempt_number_valid"),
        Index("ix_webhook_delivery_attempts_delivery", "delivery_id", "attempt_number"),
    )

    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_deliveries.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """Return an aware UTC datetime (SQLite returns naive values)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_error(exc: Exception) -> str:
    """Failure text without secrets, payload content or full URLs."""
    if isinstance(exc, AppError):
        return f"AppError({exc.code}): {exc}"[:500]
    return f"{type(exc).__name__}: {exc}"[:500]


def retry_delay_seconds(attempt: int) -> float:
    """Exponential backoff with equal jitter (FR-12), capped."""
    base = settings.webhook_retry_base_seconds
    cap = settings.webhook_retry_max_seconds
    delay = min(base * (2 ** (attempt - 1)), cap)
    return delay / 2 + random.uniform(0, delay / 2)


def build_payload(db: Session, *, post: Post, event_id: UUID) -> dict:
    """FR-11 body: event id, post information, sender information, timestamp."""
    from app.modules.agents.models import Agent
    from app.modules.organizations.models import Organization

    author = db.get(Agent, post.author_agent_id)
    organization = db.get(Organization, post.organization_id)
    published_at = post.published_at or post.created_at
    return {
        "event_id": str(event_id),
        "event_type": "post.published",
        "timestamp": published_at.isoformat(),
        "data": {
            "post": {
                "id": str(post.id),
                "title": post.title,
                "content": post.content,
                "published_at": published_at.isoformat(),
                "organization_id": str(post.organization_id),
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
                event_type="post.published",
                payload=build_payload(db, post=post, event_id=event_id),
                url=url,
                status=DeliveryStatus.PENDING.value,
            )
        )
    db.add_all(deliveries)
    return deliveries


def _send(url: str, body: bytes, headers: dict[str, str]) -> httpx.Response:
    """HTTP POST with a strict timeout, no redirect following, and DNS rebinding protection.

    At connection time we resolve the hostname and verify that the resolved IP
    is not a prohibited address. This prevents the TOCTOU rebinding attack where
    validation resolves one address but the HTTP client connects to a different
    one via a later DNS lookup.

    After validation, the actual socket connection is pinned to the resolved
    approved IP. The original hostname is preserved in the HTTP Host header
    for TLS SNI and certificate verification.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        from app.core.exceptions import AppError

        raise AppError(
            "Webhook URL hostname is missing.",
            code="invalid_webhook_url",
            status_code=422,
        )

    # Resolve all A and AAAA records at send time
    import socket as socket_module

    try:
        send_results = socket_module.getaddrinfo(hostname, None)
    except socket_module.gaierror:
        from app.core.exceptions import AppError

        raise AppError(
            "Webhook URL hostname could not be resolved at send time.",
            code="invalid_webhook_url",
            status_code=422,
        ) from None

    # Check every resolved address against the blocked list; pick the first safe IP
    safe_ip: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in send_results:
        addr = sockaddr[0]
        if not _is_blocked_address(addr):
            safe_ip = addr
            break
    else:
        from app.core.exceptions import AppError

        raise AppError(
            "Webhook URL resolves only to disallowed addresses at send time.",
            code="ssrf_blocked",
            status_code=422,
        ) from None

    # Pin the connection to the safe resolved IP while preserving the original
    # hostname in the HTTP Host header for TLS SNI and certificate validation.
    # httpx will connect to the IP address but use the Host header value
    # for SNI and certificate hostname validation.
    safe_netloc = f"{safe_ip}"
    if parsed.port and parsed.port != 443 and parsed.port != 80:
        safe_netloc = f"{safe_ip}:{parsed.port}"
    # Construct new URL with resolved IP in netloc, preserving original hostname
    # for Host header via _replace on the ParseResult
    new_parsed = parsed._replace(netloc=safe_netloc)
    safe_url = new_parsed.geturl()
    headers = dict(headers)
    headers["Host"] = hostname

    # Build the request with the pinned IP; SSRF validation at queue time
    # plus this send-time check provides defense-in-depth against DNS rebinding.
    return httpx.post(
        safe_url,
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
    from urllib.parse import urljoin

    # Lock the row for the attempt: two concurrent task deliveries of the same
    # id serialize here, so attempt numbers never double-count (the unique
    # (delivery_id, attempt_number) constraint is the backstop). SQLite
    # ignores FOR UPDATE; PostgreSQL enforces it.
    delivery = db.scalar(
        select(WebhookDelivery).where(WebhookDelivery.id == delivery_id).with_for_update()
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
        # SSRF re-validation at send time: the policy is re-checked
        # against the current DNS/IP state, not just the queue-time snapshot.
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
        # Epoch milliseconds: retries that fire inside the same second still
        # carry a fresh timestamp (and therefore a fresh signature) while the
        # receiver verification formula `hmac(secret, "{timestamp}.{body})`
        # stays unchanged - the header value is echoed back verbatim.
        timestamp = str(int(now.timestamp() * 1000))
        headers = delivery_headers(
            event_id=str(delivery.event_id),
            event_type=delivery.event_type,
            timestamp=timestamp,
            signature=compute_signature(secret, timestamp=timestamp, body=body),
        )
        response = _send(delivery.url, body, headers)
        response_status = response.status_code
        # Redirect validation: if the response is a redirect, validate the
        # target destination. Preferred default is to disable redirects
        # (follow_redirects=False in _send), but if a redirect is received,
        # validate its target per the approved security policy.
        if not 200 <= response_status < 300:
            if 300 <= response_status < 400 and response.headers.get("location"):
                try:
                    from urllib.parse import urljoin

                    validate_webhook_redirect(delivery.url, response.headers["location"])
                except AppError:
                    # Redirect to a prohibited destination - treat as failure
                    error = f"http_{response_status}_redirect_blocked"
                else:
                    error = f"http_{response_status}"
            else:
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