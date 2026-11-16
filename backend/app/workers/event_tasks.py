"""Outbox relay and stream consumer tasks (Phase 6).

Both tasks are scheduled by the Celery beat schedule in
``celery_app`` and can also be triggered manually:

* ``events.publish_outbox``        — relay pending outbox rows to Redis Streams.
* ``events.consume_post_published`` — one consumer cycle for the routing group.

The beat schedule is the recovery mechanism: any row left pending by a
crashed or offline publisher/consumer is picked up on a later tick.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.events.consumers import consume_once
from app.events.outbox import OutboxEvent, OutboxStatus
from app.events.publisher import RedisStreamPublisher, publish_pending
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

RELAY_BATCH_SIZE = 100
CONSUMER_BATCH_SIZE = 10


@celery_app.task(name="events.publish_outbox")
def publish_outbox(limit: int = RELAY_BATCH_SIZE) -> dict[str, str]:
    """Move committed outbox rows into Redis Streams (stops on first failure)."""
    publisher = RedisStreamPublisher()
    try:
        with SessionLocal() as db:
            published = publish_pending(db, publisher=publisher, limit=limit)
            remaining = (
                db.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.status == OutboxStatus.PENDING.value)
                )
                or 0
            )
    finally:
        publisher.close()
    if published:
        logger.info("Outbox relay published events", extra={"published": published})
    return {"published": str(published), "remaining": str(remaining)}


@celery_app.task(name="events.consume_post_published")
def consume_post_published(count: int = CONSUMER_BATCH_SIZE) -> dict[str, str]:
    """One consumer cycle: ack post.published events after routing enqueued.

    Uses the default finite block time so the beat schedule stays responsive.
    """
    handled = consume_once(count=count)
    return {"handled": str(handled)}
