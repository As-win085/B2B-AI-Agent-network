"""Webhook delivery records and per-attempt history.

Revision ID: 0009_webhooks
Revises: 0008_outbox
Create Date: 2026-11-16

FR-10: one notification delivery record per (post, recipient agent).
FR-12: bounded retries with recorded attempts and permanently failed
deliveries — every attempt gets a history row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_webhooks"
down_revision: str | Sequence[str] | None = "0008_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_agent_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.String(length=100),
            server_default=sa.text("'post.published'"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_webhook_deliveries_organization_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name="fk_webhook_deliveries_post_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_agent_id"],
            ["agents.id"],
            name="fk_webhook_deliveries_recipient_agent_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_deliveries"),
        sa.UniqueConstraint("event_id", name="uq_webhook_deliveries_event_id"),
        # FR-12: one logical notification per (post, recipient) — duplicate
        # routing runs or retries can never create a second delivery.
        sa.UniqueConstraint(
            "post_id",
            "recipient_agent_id",
            name="uq_webhook_deliveries_post_id_recipient_agent_id",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'failed', 'dead')",
            name="webhook_delivery_status_valid",
        ),
        sa.CheckConstraint("attempts >= 0", name="webhook_delivery_attempts_valid"),
    )
    op.create_index(
        "ix_webhook_deliveries_org_created",
        "webhook_deliveries",
        ["organization_id", "created_at", "id"],
    )
    op.create_index(
        "ix_webhook_deliveries_recipient",
        "webhook_deliveries",
        ["recipient_agent_id"],
    )
    op.create_index(
        "ix_webhook_deliveries_post",
        "webhook_deliveries",
        ["post_id"],
    )
    # The sweep claim index: due pending/failed deliveries in time order.
    op.create_index(
        "ix_webhook_deliveries_status_next",
        "webhook_deliveries",
        ["status", "next_attempt_at"],
    )

    op.create_table(
        "webhook_delivery_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["webhook_deliveries.id"],
            name="fk_webhook_delivery_attempts_delivery_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_delivery_attempts"),
        sa.CheckConstraint("attempt_number >= 1", name="webhook_attempt_number_valid"),
    )
    op.create_index(
        "ix_webhook_delivery_attempts_delivery",
        "webhook_delivery_attempts",
        ["delivery_id", "attempt_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_delivery_attempts_delivery",
        table_name="webhook_delivery_attempts",
    )
    op.drop_table("webhook_delivery_attempts")
    op.drop_index("ix_webhook_deliveries_status_next", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_post", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_recipient", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_org_created", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
