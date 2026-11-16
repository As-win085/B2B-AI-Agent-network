"""Shared pytest configuration.

Unit tests must run on a fresh clone without a real ``.env`` and without live
infrastructure. Required settings are therefore provided here before any
application module is imported.

Integration tests (``RUN_INTEGRATION_TESTS=1``) deliberately keep the real
``DATABASE_URL``/``REDIS_URL``/``RABBITMQ_URL`` from the environment or ``.env``.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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


@pytest.fixture()
def sqlite_session_factory() -> Generator[sessionmaker[Session], None, None]:
    """In-memory SQLite database with the full ORM schema.

    ``StaticPool`` keeps a single connection alive so every request in a test
    sees the same database.
    """

    import app.models  # noqa: F401 - registers every model on Base.metadata
    from app.core.database import Base

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def db(sqlite_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """A direct session for service-level tests."""

    with sqlite_session_factory() as session:
        yield session


@pytest.fixture()
def api_client(sqlite_session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    """TestClient backed by the SQLite fixture instead of PostgreSQL."""

    from app.core.database import get_db
    from app.main import create_app

    test_app = create_app()

    def _get_db() -> Generator[Session, None, None]:
        session = sqlite_session_factory()
        try:
            yield session
        finally:
            session.close()

    test_app.dependency_overrides[get_db] = _get_db
    with TestClient(test_app) as client:
        yield client
    test_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _stub_background_task_enqueues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests hermetic: API handlers must never reach RabbitMQ.

    Agent registration/manifesto updates enqueue ``agents.embed_manifesto``.
    The stub is replaced per-test by explicit ``@patch`` decorators when a test
    needs to assert on the enqueue itself. Integration runs (real broker
    available) keep the real task.
    """
    if _RUN_INTEGRATION:
        return
    from unittest.mock import MagicMock

    monkeypatch.setattr("app.modules.agents.router.embed_manifesto", MagicMock())


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
