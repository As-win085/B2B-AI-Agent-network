"""Redis Streams publisher for domain events."""

from __future__ import annotations

from typing import Any

import redis

from app.core.config import settings

POST_PUBLISHED_STREAM = "asama:events:post.published"


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
