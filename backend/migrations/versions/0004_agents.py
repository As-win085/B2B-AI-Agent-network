"""Agents and agent credentials (Phase 4).

Revision ID: 0004_agents
Revises: 0003_auth_sessions
Create Date: 2026-11-14

Adds:
  agents              -- AI agent profiles owned by an organization.
  agent_credentials   -- Hashed machine-to-machine API keys.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_agents"
down_revision: str | Sequence[str] | None = "0003_auth_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("industry_category", sa.String(length=100), nullable=True),
        sa.Column("interest_manifesto", sa.Text(), nullable=True),
        sa.Column("webhook_url", sa.String(length=2048), nullable=True),
        sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_agents"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_agents_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deactivated')",
            name="agent_status_valid",
        ),
    )
    op.create_index("ix_agents_organization_id", "agents", ["organization_id"])
    op.create_index("ix_agents_status", "agents", ["status"])

    op.create_table(
        "agent_credentials",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("credential_prefix", sa.String(length=8), nullable=False),
        sa.Column("credential_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_agent_credentials"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_credentials_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("credential_hash", name="uq_agent_credentials_credential_hash"),
    )
    op.create_index("ix_agent_credentials_agent_id", "agent_credentials", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_credentials_agent_id", table_name="agent_credentials")
    op.drop_table("agent_credentials")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_organization_id", table_name="agents")
    op.drop_table("agents")
