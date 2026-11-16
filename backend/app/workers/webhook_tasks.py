"""Webhook delivery tasks (Phase 7).

* ``webhooks.deliver``  — one signed HTTP attempt for one delivery record.
* ``webhooks.sweep``    — re-enqueue due pending/failed deliveries (beat).

The sweep (Celery beat, every 5 s) is the retry engine: backoff schedules,
worker restarts and broker outages are all absorbed because retry state lives
in the ``webhook_deliveries`` table, not in task memory. Enqueueing is
best-effort everywhere — the row always persists first.
"""

from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.modules.webhooks import service
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="webhooks.deliver")
def deliver(delivery_id: str) -> dict[str, str]:
    """Execute one delivery attempt (idempotent: delivered rows are skipped)."""
    from uuid import UUID

    with SessionLocal() as db:
        outcome = service.deliver(db, delivery_id=UUID(delivery_id))
    if outcome not in {"delivered", "already_delivered"}:
        logger.info(
            "Webhook delivery attempt finished",
            extra={"delivery_id": delivery_id, "outcome": outcome},
        )
    return {"delivery_id": delivery_id, "outcome": outcome}


@celery_app.task(name="webhooks.sweep")
def sweep() -> dict[str, str]:
    """Enqueue every delivery whose backoff window has elapsed."""
    with SessionLocal() as db:
        due = service.sweep_due(db)
    for delivery_id in due:
        service.enqueue_delivery(delivery_id)
    if due:
        logger.info("Webhook sweep enqueued deliveries", extra={"due": len(due)})
    return {"due": str(len(due))}
