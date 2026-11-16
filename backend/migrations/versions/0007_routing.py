"""Agent embedding versions, routing decisions and blocking relationships.

Revision ID: 0007_routing
Revises: 0006_comments
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0007_routing"
down_revision: str | Sequence[str] | None = "0006_comments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Generation guard for stale manifesto-embedding writes (mirrors posts).
    op.add_column(
        "agents",
        sa.Column(
            "embedding_generation",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )

    op.create_table(
        "agent_embedding_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_embedding_versions"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_embedding_versions_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "agent_id",
            "generation",
            name="uq_agent_embedding_versions_agent_id_generation",
        ),
    )
    op.create_index(
        "ix_agent_embedding_versions_agent_id_generation",
        "agent_embedding_versions",
        ["agent_id", "generation"],
    )
    op.create_index(
        "ix_agent_embedding_versions_embedding_hnsw",
        "agent_embedding_versions",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "routing_logs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("decision_reason", sa.String(length=80), nullable=False),
        sa.Column("embedding_provider", sa.String(length=40), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_generation", sa.Integer(), nullable=False),
        sa.Column("reranker_provider", sa.String(length=40), nullable=True),
        sa.Column("reranker_model", sa.String(length=100), nullable=True),
        sa.Column("rerank_status", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_routing_logs"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_routing_logs_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], name="fk_routing_logs_post_id_posts", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="fk_routing_logs_agent_id_agents", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("post_id", "agent_id", name="uq_routing_logs_post_id_agent_id"),
        sa.CheckConstraint(
            "decision IN ('selected', 'rejected')",
            name="routing_log_decision_valid",
        ),
        sa.CheckConstraint(
            "rerank_status IN ('completed', 'skipped_unconfigured', 'failed')",
            name="routing_log_rerank_status_valid",
        ),
        sa.CheckConstraint("rank IS NULL OR rank >= 1", name="routing_log_rank_valid"),
    )
    op.create_index("ix_routing_logs_organization_id", "routing_logs", ["organization_id"])
    op.create_index(
        "ix_routing_logs_post_org_created",
        "routing_logs",
        ["post_id", "organization_id", "created_at", "id"],
    )
    op.create_index(
        "ix_routing_logs_agent_created",
        "routing_logs",
        ["agent_id", "created_at", "id"],
    )

    op.create_table(
        "agent_blocks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_agent_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_blocks"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_agent_blocks_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blocked_agent_id"],
            ["agents.id"],
            name="fk_agent_blocks_blocked_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "blocked_agent_id",
            name="uq_agent_blocks_organization_id_blocked_agent_id",
        ),
    )
    op.create_index("ix_agent_blocks_organization_id", "agent_blocks", ["organization_id"])
    op.create_index("ix_agent_blocks_blocked_agent_id", "agent_blocks", ["blocked_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_blocks_blocked_agent_id", table_name="agent_blocks")
    op.drop_index("ix_agent_blocks_organization_id", table_name="agent_blocks")
    op.drop_table("agent_blocks")

    op.drop_index("ix_routing_logs_agent_created", table_name="routing_logs")
    op.drop_index("ix_routing_logs_post_org_created", table_name="routing_logs")
    op.drop_index("ix_routing_logs_organization_id", table_name="routing_logs")
    op.drop_table("routing_logs")

    op.drop_index(
        "ix_agent_embedding_versions_embedding_hnsw", table_name="agent_embedding_versions"
    )
    op.drop_index(
        "ix_agent_embedding_versions_agent_id_generation", table_name="agent_embedding_versions"
    )
    op.drop_table("agent_embedding_versions")

    op.drop_column("agents", "embedding_generation")
