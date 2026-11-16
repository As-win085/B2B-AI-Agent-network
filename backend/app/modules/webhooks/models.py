"""Webhook delivery models (Phase 7).

``WebhookDelivery`` is the FR-10 notification delivery record: one row per
(post, recipient agent) with a stable ``event_id`` so retries carry the same
identity and receivers can deduplicate (FR-11/FR-12). ``status`` follows the
delivery lifecycle ``pending → delivered | failed → dead``; every attempt is
appended to ``webhook_delivery_attempts`` (FR-12 "record every attempt").
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DeliveryStatus(StrEnum):
    """Lifecycle of one webhook delivery record."""

    PENDING = "pending"  # queued, first attempt not yet successful
    DELIVERED = "delivered"  # endpoint returned 2xx (FR-16 NOTIFIED)
    FAILED = "failed"  # last attempt failed; will retry with backoff
    DEAD = "dead"  # bounded retries exhausted (FR-12 permanent failure)


_DELIVERY_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in DeliveryStatus)


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
            f"status IN ({_DELIVERY_STATUS_VALUES})",
            name="webhook_delivery_status_valid",
        ),
        CheckConstraint("attempts >= 0", name="webhook_delivery_attempts_valid"),
        Index("ix_webhook_deliveries_org_created", "organization_id", "created_at", "id"),
        Index("ix_webhook_deliveries_recipient", "recipient_agent_id"),
        Index("ix_webhook_deliveries_post", "post_id"),
        Index("ix_webhook_deliveries_status_next", "status", "next_attempt_at"),
    )

    # Stable across attempts — the receiver's idempotency key (X-Asama-Event-Id).
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
    # Signed request body snapshot — stable across retries so signatures only
    # differ by the signed timestamp header.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # URL snapshot validated by SSRF policy at queue time and re-checked
    # immediately before every send.
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
        server_default=text("now()"),
    )
