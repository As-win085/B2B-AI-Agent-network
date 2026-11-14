"""Verify Redis connectivity and stream publish/read.

Run from the ``backend`` directory:

    python -m scripts.smoke_redis
"""

from __future__ import annotations

import uuid

import redis

from app.core.config import settings

SMOKE_STREAM = "asama:smoke:events"


def check() -> dict[str, str]:
    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )
    try:
        client.ping()
        event_id = client.xadd(
            SMOKE_STREAM,
            {"event_type": "smoke.test", "event_id": str(uuid.uuid4())},
        )
        entries = client.xrange(SMOKE_STREAM, min=event_id, max=event_id)
        client.delete(SMOKE_STREAM)
    finally:
        client.close()

    if not entries:
        raise RuntimeError("Redis stream entry was not readable after publish")

    return {"stream": SMOKE_STREAM, "entry_id": str(event_id), "entries": str(len(entries))}


def main() -> None:
    details = check()
    print("Redis: OK")
    print(f"  stream   : {details['stream']}")
    print(f"  entry id : {details['entry_id']}")


if __name__ == "__main__":
    main()
