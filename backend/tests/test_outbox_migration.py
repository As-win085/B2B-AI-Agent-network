"""Verify outbox migration upgrade/downgrade in a disposable SQLite database."""

from __future__ import annotations

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_outbox_migration_upgrade_and_downgrade_are_reversible() -> None:
    import app.models  # noqa: F401 - register all parent and target models
    from app.core.database import Base

    engine = create_engine("sqlite+pysqlite://")
    try:
        with engine.begin() as connection:
            parent_tables = [
                table for name, table in Base.metadata.tables.items() if name != "outbox_events"
            ]
            Base.metadata.create_all(connection, tables=parent_tables)
            migration = importlib.import_module("migrations.versions.0008_outbox")
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()

            inspector = inspect(connection)
            assert "outbox_events" in set(inspector.get_table_names())

            columns = {column["name"] for column in inspector.get_columns("outbox_events")}
            assert {
                "id",
                "aggregate_type",
                "aggregate_id",
                "event_type",
                "payload",
                "status",
                "attempts",
                "last_error",
                "created_at",
                "updated_at",
                "published_at",
            } <= columns

            # Status/attempt integrity checks and the relay's claim index.
            checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints("outbox_events")
            }
            assert {"outbox_event_status_valid", "outbox_event_attempts_valid"} <= checks
            indexes = {index["name"] for index in inspector.get_indexes("outbox_events")}
            assert {"ix_outbox_events_status_created", "ix_outbox_events_aggregate"} <= indexes

            # Defaults: a staged row is pending with zero attempts.
            status_default = next(
                column["default"]
                for column in inspector.get_columns("outbox_events")
                if column["name"] == "status"
            )
            assert "pending" in str(status_default)

            with Operations.context(context):
                migration.downgrade()

            inspector = inspect(connection)
            assert "outbox_events" not in set(inspector.get_table_names())
    finally:
        engine.dispose()
