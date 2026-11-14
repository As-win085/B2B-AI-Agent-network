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
    include=["app.workers.routing_tasks", "app.workers.webhook_tasks"],
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
)
