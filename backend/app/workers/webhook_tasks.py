"""Webhook delivery tasks (Phase 7).

Sprint 1 registers a connectivity test task only.
"""

from __future__ import annotations

from app.workers.celery_app import celery_app


@celery_app.task(name="webhooks.ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "worker": "webhooks"}
