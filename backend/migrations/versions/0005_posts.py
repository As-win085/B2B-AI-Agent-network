"""Posts with tenant ownership and embeddings.

Revision ID: 0005_posts
Revises: 0004_agents
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0005_posts"
down_revision: str | Sequence[str] | None = "0004_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "posts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("author_agent_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'processing'"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("embedding_provider", sa.String(length=40), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column(
            "embedding_generation", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_posts"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_posts_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_agent_id"],
            ["agents.id"],
            name="fk_posts_author_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'published', 'failed', 'archived')",
            name="post_status_valid",
        ),
    )
    op.create_index("ix_posts_organization_id", "posts", ["organization_id"])
    op.create_index("ix_posts_author_agent_id", "posts", ["author_agent_id"])
    op.create_index("ix_posts_status", "posts", ["status"])
    op.create_index(
        "ix_posts_embedding_hnsw",
        "posts",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_posts_embedding_hnsw", table_name="posts")
    op.drop_index("ix_posts_status", table_name="posts")
    op.drop_index("ix_posts_author_agent_id", table_name="posts")
    op.drop_index("ix_posts_organization_id", table_name="posts")
    op.drop_table("posts")
