"""Verify RabbitMQ connectivity with a publish/consume round-trip.

Run from the ``backend`` directory:

    python -m scripts.smoke_rabbitmq
"""

from __future__ import annotations

import uuid

from kombu import Connection, Queue

from app.core.config import settings

SMOKE_QUEUE = "asama.smoke"


def check() -> dict[str, str]:
    queue = Queue(SMOKE_QUEUE, routing_key=SMOKE_QUEUE)
    token = str(uuid.uuid4())

    with Connection(settings.rabbitmq_url, connect_timeout=5) as connection:
        connection.ensure_connection(max_retries=2)
        producer = connection.Producer(serializer="json")
        producer.publish(
            {"event_type": "smoke.test", "token": token},
            exchange="",
            routing_key=SMOKE_QUEUE,
            declare=[queue],
        )

        simple_queue = connection.SimpleQueue(queue)
        try:
            message = simple_queue.get(timeout=5)
            payload = message.payload
            message.ack()
        finally:
            simple_queue.close()

    if payload.get("token") != token:
        raise RuntimeError("RabbitMQ round-trip returned an unexpected payload")

    return {"queue": SMOKE_QUEUE, "token": token}


def main() -> None:
    details = check()
    print("RabbitMQ: OK")
    print(f"  queue    : {details['queue']}")


if __name__ == "__main__":
    main()
