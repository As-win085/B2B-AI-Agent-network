"""Transactional outbox (Phase 6).

A post and its ``post.published`` outbox row are committed in the same database
transaction (:func:`record_event` adds the row without committing, so the
caller's commit covers both). A separate publisher
(:func:`app.events.publisher.publish_pending`) moves committed outbox rows
into Redis Streams and marks them published.

Rows are never deleted on failure: a publisher outage leaves them ``pending``
with an incremented ``attempts`` counter, so committed events cannot be lost
(release gate 3). Delivery is at-least-once — consumers must be idempotent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class OutboxStatus(StrEnum):
    """Lifecycle of one outbox row."""

    PENDING = "pending"
    PUBLISHED = "published"


_OUTBOX_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in OutboxStatus)

# Event types the relay knows how to route to a stream.
POST_PUBLISHED = "post.published"


class OutboxEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One domain event awaiting (or having completed) stream publication."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_OUTBOX_STATUS_VALUES})",
            name="outbox_event_status_valid",
        ),
        CheckConstraint("attempts >= 0", name="outbox_event_attempts_valid"),
        Index("ix_outbox_events_status_created", "status", "created_at", "id"),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
    )

    # Polymorphic aggregate reference (no FK): events outlive their aggregate
    # and the payload carries the identifiers consumers need.
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
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
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


def record_event(
    db: Session,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> OutboxEvent:
    """Stage an outbox row in the caller's transaction.

    The row becomes durable only when the caller commits — this is what makes
    the business write and the event atomic.
    """
    event = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        status=OutboxStatus.PENDING.value,
    )
    db.add(event)
    return event


def pending_events(db: Session, *, limit: int) -> list[OutboxEvent]:
    """Oldest-first pending rows (creation order preserved per aggregate)."""
    return list(
        db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING.value)
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
        ).all()
    )


def mark_published(event: OutboxEvent) -> None:
    event.status = OutboxStatus.PUBLISHED.value
    event.attempts += 1
    event.published_at = datetime.now(UTC)
    event.last_error = None


def mark_publish_failed(event: OutboxEvent, error: str) -> None:
    """Record a failed delivery attempt; the row stays pending for retry."""
    event.attempts += 1
    event.last_error = error[:500]
