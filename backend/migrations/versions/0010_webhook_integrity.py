"""Webhook delivery integrity fixups.

Revision ID: 0010_webhook_integrity
Revises: 0009_webhooks
Create Date: 2026-11-16

``0009_webhooks`` was applied before ``alembic check`` was run and turned out
to be missing two objects the model metadata declares:

* ``ix_webhook_deliveries_organization_id`` — the TenantMixin single-column
  tenant index (present on every other tenant-owned table);
* ``uq_webhook_delivery_attempts_delivery_id_attempt_number`` — one history
  row per attempt of a delivery.

The foreign keys ``0009`` created were missing only from the model side and
were fixed in code, so no FK changes happen here. ``0009`` itself is left
untouched because it is already applied (never edit applied migrations).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_webhook_integrity"
down_revision: str | Sequence[str] | None = "0009_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_webhook_deliveries_organization_id",
        "webhook_deliveries",
        ["organization_id"],
    )
    op.create_unique_constraint(
        "uq_webhook_delivery_attempts_delivery_id_attempt_number",
        "webhook_delivery_attempts",
        ["delivery_id", "attempt_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_webhook_delivery_attempts_delivery_id_attempt_number",
        "webhook_delivery_attempts",
        type_="unique",
    )
    op.drop_index(
        "ix_webhook_deliveries_organization_id",
        table_name="webhook_deliveries",
    )
