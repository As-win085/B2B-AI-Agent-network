"""Routing tasks (Phase 5–6).

``routing.route_post`` executes the routing engine for one post. Phase 6 will
enqueue it from the ``post.published`` outbox event; there is deliberately no
client API that triggers routing manually.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.database import SessionLocal
from app.modules.routing import service as routing_service
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="routing.route_post")
def route_post(post_id: str) -> dict[str, str]:
    """Route one post through eligibility, retrieval, reranking and logging."""
    with SessionLocal() as db:
        outcome = routing_service.route_post(db, post_id=UUID(post_id))
    if not outcome.routed and outcome.reason not in {"already_routed"}:
        logger.info(
            "Routing skipped",
            extra={"post_id": post_id, "reason": outcome.reason},
        )
    return {
        "post_id": post_id,
        "routed": str(outcome.routed).lower(),
        "reason": outcome.reason or "",
        "candidates": str(outcome.candidates),
        "selected": str(outcome.selected),
        "rerank_status": outcome.rerank_status or "",
    }
