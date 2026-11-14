"""Routing tasks (Phase 5–6).

Sprint 1 registers a connectivity test task only. Eligibility filtering,
vector retrieval and reranking run here in later phases.
"""

from __future__ import annotations

from app.workers.celery_app import celery_app


@celery_app.task(name="routing.ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "worker": "routing"}
