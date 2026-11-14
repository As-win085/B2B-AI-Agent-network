"""Shared pytest configuration.

Unit tests must run on a fresh clone without a real ``.env`` and without live
infrastructure. Required settings are therefore provided here before any
application module is imported.

Integration tests (``RUN_INTEGRATION_TESTS=1``) deliberately keep the real
``DATABASE_URL``/``REDIS_URL``/``RABBITMQ_URL`` from the environment or ``.env``.
"""

from __future__ import annotations

import os

import pytest

_RUN_INTEGRATION = os.getenv("RUN_INTEGRATION_TESTS") == "1"

# Hermetic defaults for unit tests. ``setdefault`` means explicit environment
# values still win; pydantic-settings also gives OS environment precedence over
# the repository ``.env`` file.
if not _RUN_INTEGRATION:
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://asama:asama_local_dev@localhost:5433/asama_test?sslmode=require",
    )

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-not-for-production")
os.environ.setdefault("WEBHOOK_SECRET_ENCRYPTION_KEY", "test-webhook-encryption-key-not-secret")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _RUN_INTEGRATION:
        return
    skip_integration = pytest.mark.skip(
        reason=(
            "set RUN_INTEGRATION_TESTS=1 and start PostgreSQL/Redis/RabbitMQ "
            "to run integration tests"
        )
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
