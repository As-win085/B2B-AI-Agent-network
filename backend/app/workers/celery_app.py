"""Celery application.

Redis Streams carries domain events; RabbitMQ carries Celery task messages.
Do not publish domain events directly to RabbitMQ.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "asama",
    broker=settings.rabbitmq_url,
    backend=None,
    include=[
        "app.workers.routing_tasks",
        "app.workers.webhook_tasks",
        "app.workers.post_tasks",
        "app.workers.agent_tasks",
        "app.workers.event_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
    task_default_queue="asama.tasks",
    broker_connection_retry_on_startup=True,
    # Recovery schedule for the outbox relay and the stream consumer: any
    # pending row or unacknowledged message is picked up on a later tick, so
    # committed events are never lost when a worker is temporarily offline.
    beat_schedule={
        "outbox-publish": {
            "task": "events.publish_outbox",
            "schedule": 5.0,
        },
        "consume-post-published": {
            "task": "events.consume_post_published",
            "schedule": 2.0,
        },
        # Webhook retry engine: re-enqueues deliveries whose backoff elapsed.
        "webhook-sweep": {
            "task": "webhooks.sweep",
            "schedule": 5.0,
        },
    },
)
