"""Baseline: enable the pgvector extension.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-14

Sprint 1 applies only the baseline migration. Tenant tables, embeddings and
routing tables are introduced in Phases 2–6.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Do not drop a shared extension automatically; other schemas may use it.
    pass
