"""Verify comments migration upgrade/downgrade in a disposable SQLite database."""

from __future__ import annotations

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_comments_migration_upgrade_and_downgrade_are_reversible() -> None:
    import app.models  # noqa: F401 - register all parent and target models
    from app.core.database import Base

    engine = create_engine("sqlite+pysqlite://")
    try:
        with engine.begin() as connection:
            parent_tables = [
                table for name, table in Base.metadata.tables.items() if name != "comments"
            ]
            Base.metadata.create_all(connection, tables=parent_tables)
            migration = importlib.import_module("migrations.versions.0006_comments")
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()

            inspector = inspect(connection)
            assert "comments" in inspector.get_table_names()
            assert {"organization_id", "post_id", "author_agent_id", "content"} <= set(
                inspector.get_columns("comments")[i]["name"]
                for i in range(len(inspector.get_columns("comments")))
            )
            foreign_keys = inspector.get_foreign_keys("comments")
            assert {tuple(item["constrained_columns"]) for item in foreign_keys} == {
                ("organization_id",),
                ("post_id",),
                ("author_agent_id",),
            }
            assert all(item["options"].get("ondelete") == "CASCADE" for item in foreign_keys)
            indexes = {item["name"] for item in inspector.get_indexes("comments")}
            assert "ix_comments_post_org_created" in indexes
            assert "ix_comments_author_agent_id" in indexes
            assert "ix_comments_organization_id" in indexes

            with Operations.context(context):
                migration.downgrade()
            assert "comments" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()
