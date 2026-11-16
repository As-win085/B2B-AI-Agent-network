"""Redis Streams publisher for domain events.

:func:`publish_pending` is the outbox relay: it moves committed ``pending``
rows into their Redis Stream in creation order and marks them published. The
relay stops at the first failure so per-aggregate ordering is preserved; the
failed row stays ``pending`` with an incremented attempt counter and is
retried on the next run (recovery after a publisher outage — release gate 3).

Delivery is at-least-once: a crash between ``xadd`` and the marking commit
re-publishes the row later, so consumers must treat duplicates as normal.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.events.outbox import (
    POST_PUBLISHED,
    OutboxEvent,
    mark_publish_failed,
    mark_published,
    pending_events,
)

logger = logging.getLogger(__name__)

POST_PUBLISHED_STREAM = "asama:events:post.published"

# One stream per event type; new event types register here.
STREAM_BY_EVENT_TYPE: dict[str, str] = {
    POST_PUBLISHED: POST_PUBLISHED_STREAM,
}


class RedisStreamPublisher:
    def __init__(self, url: str | None = None) -> None:
        self._client = redis.Redis.from_url(
            url or settings.redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
            decode_responses=True,
        )

    def publish(self, stream: str, event: dict[str, Any]) -> str:
        payload = {key: str(value) for key, value in event.items()}
        return self._client.xadd(stream, payload)

    def close(self) -> None:
        self._client.close()


def event_fields(event: OutboxEvent) -> dict[str, str]:
    """Serialize an outbox row into Redis Stream fields (all strings)."""
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": str(event.aggregate_id),
        "payload": json.dumps(event.payload, sort_keys=True),
        "created_at": event.created_at.isoformat(),
    }


def _safe_error(exc: Exception) -> str:
    """Failure text without payload content or credentials."""
    return f"{type(exc).__name__}: {exc}"[:500]


def publish_pending(
    db: Session,
    *,
    publisher: RedisStreamPublisher,
    limit: int = 100,
) -> int:
    """Publish up to ``limit`` pending outbox rows in creation order.

    Returns the number of rows marked published. The first failure stops the
    batch (ordering) and leaves that row pending for the next run.
    """
    events = pending_events(db, limit=limit)
    published = 0
    for event in events:
        stream = STREAM_BY_EVENT_TYPE.get(event.event_type)
        if stream is None:
            # Programming error: an event type with no stream mapping would
            # otherwise poison the relay forever — surface it loudly and stop.
            logger.error(
                "No stream mapping for outbox event type",
                extra={"event_id": str(event.id), "event_type": event.event_type},
            )
            mark_publish_failed(event, "unmapped_event_type")
            db.commit()
            break
        try:
            publisher.publish(stream, event_fields(event))
        except Exception as exc:  # noqa: BLE001 - relay must survive broker outages
            mark_publish_failed(event, _safe_error(exc))
            db.commit()
            logger.warning(
                "Outbox publish failed; event stays pending",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "attempts": event.attempts,
                },
            )
            break
        mark_published(event)
        published += 1
    db.commit()
    return published


def trigger_publish_outbox() -> None:
    """Best-effort immediate relay run; the beat schedule recovers anything
    this misses (broker or Redis momentarily unavailable)."""
    from app.workers.event_tasks import publish_outbox

    try:
        publish_outbox.delay()
    except Exception:  # noqa: BLE001 - never fail the caller; outbox persists
        logger.warning("Outbox relay trigger failed; beat schedule will retry")
