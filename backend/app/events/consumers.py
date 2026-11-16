"""Redis Streams consumers: consumer groups, acknowledgement, recovery.

Consumers read their stream through a group (``XREADGROUP``), acknowledge a
message only after its handler succeeded (``XACK``), and recover messages
abandoned by a crashed worker via ``XAUTOCLAIM`` after a minimum idle time.
A message whose handler fails simply stays pending and is redelivered later.

Handlers must be idempotent: redelivery after a crash between handler success
and ack is expected (at-least-once semantics).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis
from redis.exceptions import ResponseError

from app.core.config import settings
from app.events.publisher import POST_PUBLISHED_STREAM

logger = logging.getLogger(__name__)

# One group per downstream consumer family. The routing consumer owns the
# post.published stream; Phase 7 adds webhook/notification groups.
ROUTING_GROUP = "asama-routing"

DEFAULT_COUNT = 10
DEFAULT_BLOCK_MS = 250
DEFAULT_MIN_IDLE_MS = 30_000


def get_client(url: str | None = None) -> redis.Redis:
    return redis.Redis.from_url(
        url or settings.redis_url,
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )


def ensure_consumer_group(
    client: redis.Redis, stream: str, group: str, *, start_id: str = "0"
) -> None:
    """Create the group (and stream) if missing; tolerate an existing group."""
    try:
        client.xgroup_create(stream, group, id=start_id, mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _entries_from_xautoclaim(result: Any) -> list[tuple[str, dict[str, str]]]:
    """redis-py returns (next_id, entries[, deleted]) — entries are [id, fields]."""
    entries = result[1] if isinstance(result, (tuple, list)) else []
    return [(entry[0], entry[1]) for entry in entries]


def claim_stale(
    client: redis.Redis,
    stream: str,
    group: str,
    consumer: str,
    *,
    min_idle_ms: int,
    count: int,
) -> list[tuple[str, dict[str, str]]]:
    """Recover messages another consumer left pending for too long."""
    result = client.xautoclaim(
        stream,
        group,
        consumer,
        min_idle_time=min_idle_ms,
        start_id="0-0",
        count=count,
    )
    return _entries_from_xautoclaim(result)


def read_new(
    client: redis.Redis,
    stream: str,
    group: str,
    consumer: str,
    *,
    count: int,
    block_ms: int,
) -> list[tuple[str, dict[str, str]]]:
    """Read messages never delivered to this group (``>``)."""
    # redis-py treats BLOCK 0 as "block forever" — map 0/None to a
    # non-blocking read instead.
    block = block_ms if block_ms and block_ms > 0 else None
    response = client.xreadgroup(
        group,
        consumer,
        {stream: ">"},
        count=count,
        block=block,
    )
    if not response:
        return []
    _stream_name, entries = response[0]
    return [(entry[0], entry[1]) for entry in entries]


def dispatch(fields: dict[str, str]) -> None:
    """Run the handler for one event. Raises when the handler failed."""
    event_type = fields.get("event_type", "")
    if event_type == "post.published":
        payload = json.loads(fields.get("payload", "{}"))
        post_id = payload.get("post_id")
        if not post_id:
            raise ValueError("post.published event without post_id")
        from app.workers.routing_tasks import route_post

        # Enqueue only; route_post itself is idempotent per post, so a
        # duplicate delivery after a crash is harmless (release gate 4).
        route_post.delay(post_id)
        return
    raise ValueError(f"Unknown event type: {event_type}")


def _handle(client: redis.Redis, stream: str, group: str, entry_id: str, fields: dict) -> bool:
    try:
        dispatch(fields)
    except Exception:  # noqa: BLE001 - a failed handler must stay pending
        logger.warning(
            "Event handling failed; leaving message pending",
            extra={"stream": stream, "entry_id": entry_id},
        )
        return False
    client.xack(stream, group, entry_id)
    return True


def consume_once(
    *,
    client: redis.Redis | None = None,
    stream: str = POST_PUBLISHED_STREAM,
    group: str = ROUTING_GROUP,
    consumer: str = "routing-1",
    count: int = DEFAULT_COUNT,
    block_ms: int = DEFAULT_BLOCK_MS,
    min_idle_ms: int = DEFAULT_MIN_IDLE_MS,
) -> int:
    """One receive cycle: recover stale messages, then read new ones.

    Returns the number of messages acknowledged (handler succeeded).
    """
    owns_client = client is None
    client = client or get_client()
    try:
        ensure_consumer_group(client, stream, group)
        handled = 0
        for entry_id, fields in claim_stale(
            client, stream, group, consumer, min_idle_ms=min_idle_ms, count=count
        ):
            if _handle(client, stream, group, entry_id, fields):
                handled += 1
        for entry_id, fields in read_new(
            client, stream, group, consumer, count=count, block_ms=block_ms
        ):
            if _handle(client, stream, group, entry_id, fields):
                handled += 1
        return handled
    finally:
        if owns_client:
            client.close()
