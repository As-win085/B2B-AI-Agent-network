"""Verify routing migration upgrade/downgrade in a disposable SQLite database."""

from __future__ import annotations

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_routing_migration_upgrade_and_downgrade_are_reversible() -> None:
    import app.models  # noqa: F401 - register all parent and target models
    from app.core.database import Base

    engine = create_engine("sqlite+pysqlite://")
    try:
        with engine.begin() as connection:
            new_tables = {
                "agent_embedding_versions",
                "routing_logs",
                "agent_blocks",
            }
            parent_tables = [
                table for name, table in Base.metadata.tables.items() if name not in new_tables
            ]
            Base.metadata.create_all(connection, tables=parent_tables)
            # The ORM metadata already contains agents.embedding_generation;
            # drop it so the pre-migration state is reproduced faithfully.
            connection.exec_driver_sql("ALTER TABLE agents DROP COLUMN embedding_generation")

            migration = importlib.import_module("migrations.versions.0007_routing")
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()

            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            assert new_tables <= tables

            # agents gained the stale-write generation guard.
            agent_columns = {column["name"] for column in inspector.get_columns("agents")}
            assert "embedding_generation" in agent_columns

            # agent_embedding_versions: versioned vectors with a per-agent
            # generation uniqueness rule and an HNSW index on PostgreSQL.
            version_columns = {
                column["name"] for column in inspector.get_columns("agent_embedding_versions")
            }
            assert {
                "id",
                "agent_id",
                "embedding",
                "provider",
                "model",
                "dimensions",
                "generation",
                "created_at",
            } <= version_columns
            version_uniques = {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints("agent_embedding_versions")
            }
            assert ("agent_id", "generation") in version_uniques
            version_indexes = {
                index["name"] for index in inspector.get_indexes("agent_embedding_versions")
            }
            assert "ix_agent_embedding_versions_agent_id_generation" in version_indexes

            # routing_logs: explainable decisions with uniqueness per pair.
            log_columns = {column["name"] for column in inspector.get_columns("routing_logs")}
            assert {
                "organization_id",
                "post_id",
                "agent_id",
                "similarity_score",
                "rerank_score",
                "rank",
                "decision",
                "decision_reason",
                "embedding_provider",
                "embedding_model",
                "embedding_generation",
                "reranker_provider",
                "reranker_model",
                "rerank_status",
                "created_at",
            } <= log_columns
            log_uniques = {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints("routing_logs")
            }
            assert ("post_id", "agent_id") in log_uniques
            log_foreign_keys = {
                tuple(fk["constrained_columns"])
                for fk in inspector.get_foreign_keys("routing_logs")
            }
            assert log_foreign_keys == {
                ("organization_id",),
                ("post_id",),
                ("agent_id",),
            }
            assert all(
                fk["options"].get("ondelete") == "CASCADE"
                for fk in inspector.get_foreign_keys("routing_logs")
            )
            log_indexes = {index["name"] for index in inspector.get_indexes("routing_logs")}
            assert {
                "ix_routing_logs_organization_id",
                "ix_routing_logs_post_org_created",
                "ix_routing_logs_agent_created",
            } <= log_indexes

            # agent_blocks: organization blocks an agent, once.
            block_columns = {column["name"] for column in inspector.get_columns("agent_blocks")}
            assert {
                "organization_id",
                "blocked_agent_id",
                "reason",
                "created_at",
            } <= block_columns
            block_uniques = {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints("agent_blocks")
            }
            assert ("organization_id", "blocked_agent_id") in block_uniques
            block_indexes = {index["name"] for index in inspector.get_indexes("agent_blocks")}
            assert {"ix_agent_blocks_organization_id", "ix_agent_blocks_blocked_agent_id"} <= (
                block_indexes
            )

            with Operations.context(context):
                migration.downgrade()

            inspector = inspect(connection)
            assert not new_tables & set(inspector.get_table_names())
            agent_columns_after = {column["name"] for column in inspector.get_columns("agents")}
            assert "embedding_generation" not in agent_columns_after
    finally:
        engine.dispose()
