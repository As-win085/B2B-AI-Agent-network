"""Dependency checks used by the readiness endpoint.

Checks are deliberately short-timeout and never raise: a failing dependency is
reported as a degraded component instead of crashing the API process.
"""

from __future__ import annotations

import logging

from app.core.database import check_database
from app.modules.health.schemas import ComponentStatus

logger = logging.getLogger(__name__)


def _check_redis() -> ComponentStatus:
    try:
        import redis

        from app.core.config import settings

        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        client.close()
        return ComponentStatus(name="redis", ok=True)
    except Exception as exc:  # noqa: BLE001 - report, do not crash readiness
        logger.warning("Redis readiness check failed: %s", exc)
        return ComponentStatus(name="redis", ok=False, detail=type(exc).__name__)


def _check_rabbitmq() -> ComponentStatus:
    try:
        import kombu

        from app.core.config import settings

        with kombu.Connection(settings.rabbitmq_url, connect_timeout=2) as connection:
            connection.ensure_connection(max_retries=1)
        return ComponentStatus(name="rabbitmq", ok=True)
    except Exception as exc:  # noqa: BLE001 - report, do not crash readiness
        logger.warning("RabbitMQ readiness check failed: %s", exc)
        return ComponentStatus(name="rabbitmq", ok=False, detail=type(exc).__name__)


def check_dependencies() -> list[ComponentStatus]:
    components: list[ComponentStatus] = []

    try:
        check_database()
        components.append(ComponentStatus(name="postgres", ok=True))
    except Exception as exc:  # noqa: BLE001 - report, do not crash readiness
        logger.warning("PostgreSQL readiness check failed: %s", exc)
        components.append(ComponentStatus(name="postgres", ok=False, detail=type(exc).__name__))

    components.append(_check_redis())
    components.append(_check_rabbitmq())
    return components
