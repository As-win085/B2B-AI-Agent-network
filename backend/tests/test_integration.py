"""Live infrastructure tests.

These are skipped unless ``RUN_INTEGRATION_TESTS=1``. They require:
- PostgreSQL reachable via DATABASE_URL (with pgvector available)
- Redis reachable via REDIS_URL
- RabbitMQ reachable via RABBITMQ_URL
"""

from __future__ import annotations

import uuid

import pytest
import redis
from kombu import Connection, Queue
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine

pytestmark = pytest.mark.integration


def test_postgres_and_pgvector() -> None:
    with engine.begin() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
    assert version


def test_redis_stream_round_trip() -> None:
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    stream = "asama:test:events"
    try:
        client.ping()
        entry_id = client.xadd(stream, {"event_type": "test", "token": str(uuid.uuid4())})
        entries = client.xrange(stream, min=entry_id, max=entry_id)
        assert len(entries) == 1
    finally:
        client.delete(stream)
        client.close()


def test_rabbitmq_round_trip() -> None:
    queue = Queue("asama.test", routing_key="asama.test")
    token = str(uuid.uuid4())

    with Connection(settings.rabbitmq_url, connect_timeout=5) as connection:
        connection.ensure_connection(max_retries=2)
        producer = connection.Producer(serializer="json")
        producer.publish(
            {"token": token},
            exchange="",
            routing_key="asama.test",
            declare=[queue],
        )
        simple_queue = connection.SimpleQueue(queue)
        try:
            message = simple_queue.get(timeout=5)
            assert message.payload["token"] == token
            message.ack()
        finally:
            simple_queue.close()
