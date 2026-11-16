"""Background embedding task for agent interest manifestos."""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.database import SessionLocal
from app.modules.embeddings import service
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="agents.embed_manifesto")
def embed_manifesto(agent_id: str, generation: int) -> dict[str, str]:
    """Embed the manifesto for exactly ``generation``.

    The service never raises for expected failures (stale generation,
    duplicate delivery, provider outage); those are reported in the result and
    logged so operators can observe provider problems.
    """
    with SessionLocal() as db:
        outcome = service.embed_manifesto(db, agent_id=UUID(agent_id), generation=generation)
    if not outcome.stored and outcome.reason not in {
        "already_embedded",
        "empty_manifesto",
        "stale_generation",
    }:
        logger.warning(
            "Agent manifesto embedding not stored",
            extra={"agent_id": agent_id, "generation": generation, "reason": outcome.reason},
        )
    return {
        "agent_id": agent_id,
        "generation": str(generation),
        "stored": str(outcome.stored).lower(),
        "reason": outcome.reason or "",
    }
