"""Verify webhook migrations 0009 and 0010 in a disposable SQLite database."""

from __future__ import annotations

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _run_migration(connection, module_name: str, direction: str) -> None:
    migration = importlib.import_module(f"migrations.versions.{module_name}")
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def test_webhook_migrations_upgrade_and_downgrade_are_reversible() -> None:
    import app.models  # noqa: F401 - register all parent and target models
    from app.core.database import Base

    engine = create_engine("sqlite+pysqlite://")
    try:
        with engine.begin() as connection:
            parent_tables = [
                table
                for name, table in Base.metadata.tables.items()
                if name not in {"webhook_deliveries", "webhook_delivery_attempts"}
            ]
            Base.metadata.create_all(connection, tables=parent_tables)

            _run_migration(connection, "0009_webhooks", "upgrade")
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            assert {"webhook_deliveries", "webhook_delivery_attempts"} <= tables

            # FR-10 columns.
            columns = {c["name"] for c in inspector.get_columns("webhook_deliveries")}
            assert {
                "id",
                "event_id",
                "organization_id",
                "post_id",
                "recipient_agent_id",
                "event_type",
                "payload",
                "url",
                "status",
                "attempts",
                "next_attempt_at",
                "last_error",
                "response_status",
                "last_attempt_at",
                "delivered_at",
                "created_at",
                "updated_at",
            } <= columns

            checks = {
                c["name"] for c in inspector.get_check_constraints("webhook_deliveries")
            }
            assert {"webhook_delivery_status_valid", "webhook_delivery_attempts_valid"} <= checks
            uniques = {
                c["name"] for c in inspector.get_unique_constraints("webhook_deliveries")
            }
            assert {
                "uq_webhook_deliveries_event_id",
                "uq_webhook_deliveries_post_id_recipient_agent_id",
            } <= uniques

            attempt_checks = {
                c["name"] for c in inspector.get_check_constraints("webhook_delivery_attempts")
            }
            assert "webhook_attempt_number_valid" in attempt_checks

            # 0010: the tenant index and per-attempt uniqueness fixups.
            _run_migration(connection, "0010_webhook_integrity", "upgrade")
            inspector = inspect(connection)
            indexes = {i["name"] for i in inspector.get_indexes("webhook_deliveries")}
            assert "ix_webhook_deliveries_organization_id" in indexes
            assert "ix_webhook_deliveries_status_next" in indexes
            attempt_uniques = {
                c["name"]
                for c in inspector.get_unique_constraints("webhook_delivery_attempts")
            }
            assert "uq_webhook_delivery_attempts_delivery_id_attempt_number" in attempt_uniques

            # Reversibility (disposable database only — never against live PG).
            _run_migration(connection, "0010_webhook_integrity", "downgrade")
            inspector = inspect(connection)
            indexes = {i["name"] for i in inspector.get_indexes("webhook_deliveries")}
            assert "ix_webhook_deliveries_organization_id" not in indexes
            attempt_uniques = {
                c["name"]
                for c in inspector.get_unique_constraints("webhook_delivery_attempts")
            }
            assert "uq_webhook_delivery_attempts_delivery_id_attempt_number" not in attempt_uniques

            _run_migration(connection, "0009_webhooks", "downgrade")
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            assert "webhook_deliveries" not in tables
            assert "webhook_delivery_attempts" not in tables
    finally:
        engine.dispose()
