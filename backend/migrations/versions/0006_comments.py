"""Tenant-owned comments and post discussions.

Revision ID: 0006_comments
Revises: 0005_posts
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_comments"
down_revision: str | Sequence[str] | None = "0005_posts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("author_agent_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_comments"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_comments_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], name="fk_comments_post_id_posts", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_agent_id"],
            ["agents.id"],
            name="fk_comments_author_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0 AND length(content) <= 5000",
            name="comment_content_valid",
        ),
    )
    op.create_index("ix_comments_organization_id", "comments", ["organization_id"])
    op.create_index("ix_comments_author_agent_id", "comments", ["author_agent_id"])
    op.create_index(
        "ix_comments_post_org_created",
        "comments",
        ["post_id", "organization_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_comments_post_org_created", table_name="comments")
    op.drop_index("ix_comments_author_agent_id", table_name="comments")
    op.drop_index("ix_comments_organization_id", table_name="comments")
    op.drop_table("comments")
