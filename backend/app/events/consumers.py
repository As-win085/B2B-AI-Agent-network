"""Redis Streams consumer helpers (Phase 6).

Consumer groups, acknowledgement and recovery are implemented with the routing
worker in Phase 6. Sprint 1 verifies connectivity only.
"""

from __future__ import annotations

from typing import Any

import redis

from app.core.config import settings


def read_stream(
    stream: str, *, last_id: str = "0-0", count: int = 10
) -> list[tuple[str, dict[str, Any]]]:
    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )
    try:
        return client.xrange(stream, min=last_id, max="+", count=count)
    finally:
        client.close()
