"""Versioned agent interest-manifesto embeddings.

Reuses the shared :mod:`app.modules.embeddings.provider` abstraction; there is
exactly one embedding provider implementation in the codebase. This module adds
persistence and the generation guard:

* ``agents.embedding_generation`` is bumped whenever the manifesto changes.
* A write only succeeds when the task's generation is still current, so a slow
  provider call can never overwrite a newer embedding.
* ``(agent_id, generation)`` is unique, which makes duplicate task deliveries
  and backfill re-runs idempotent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.agents.models import Agent
from app.modules.embeddings.provider import (
    EmbeddingProviderError,
    get_embedding_provider,
    validate_embedding,
)
from app.modules.routing.models import AgentEmbeddingVersion

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingOutcome:
    """Result of one embedding attempt (never raises for expected failures)."""

    agent_id: UUID
    generation: int
    stored: bool
    reason: str | None = None


def _current_generation(db: Session, agent_id: UUID) -> int | None:
    return db.scalar(select(Agent.embedding_generation).where(Agent.id == agent_id))


def embed_manifesto(db: Session, *, agent_id: UUID, generation: int) -> EmbeddingOutcome:
    """Embed the agent's manifesto for ``generation`` if it is still current.

    Expected failures (provider down, stale generation, empty manifesto,
    duplicate delivery) are returned as outcomes instead of raised so a worker
    task never crashes on them. Only unexpected programming errors propagate.
    """
    agent = db.get(Agent, agent_id)
    if agent is None:
        return EmbeddingOutcome(agent_id, generation, stored=False, reason="agent_not_found")

    current = _current_generation(db, agent_id)
    if current is None or current != generation:
        return EmbeddingOutcome(agent_id, generation, stored=False, reason="stale_generation")

    manifesto = (agent.interest_manifesto or "").strip()
    if not manifesto:
        return EmbeddingOutcome(agent_id, generation, stored=False, reason="empty_manifesto")

    existing = db.scalar(
        select(AgentEmbeddingVersion).where(
            AgentEmbeddingVersion.agent_id == agent_id,
            AgentEmbeddingVersion.generation == generation,
        )
    )
    if (
        existing is not None
        and existing.provider == settings.embedding_provider
        and existing.model == settings.embedding_model
        and existing.dimensions == settings.embedding_dimensions
    ):
        # Same generation already embedded with the current model: idempotent.
        return EmbeddingOutcome(agent_id, generation, stored=False, reason="already_embedded")

    try:
        provider = get_embedding_provider()
        result = provider.embed(manifesto)
        vector = validate_embedding(result.vector, settings.embedding_dimensions)
    except EmbeddingProviderError as exc:
        logger.warning(
            "Agent manifesto embedding failed",
            extra={"agent_id": str(agent_id), "generation": generation, "reason": str(exc)},
        )
        return EmbeddingOutcome(agent_id, generation, stored=False, reason="provider_unavailable")
    except Exception:  # noqa: BLE001 - provider/task boundary must not crash workers
        logger.warning(
            "Agent manifesto embedding failed unexpectedly",
            extra={"agent_id": str(agent_id), "generation": generation},
        )
        return EmbeddingOutcome(agent_id, generation, stored=False, reason="provider_unavailable")

    # Re-check after the slow provider call: never write a stale generation.
    current = _current_generation(db, agent_id)
    if current is None or current != generation:
        return EmbeddingOutcome(agent_id, generation, stored=False, reason="stale_generation")

    if existing is not None:
        # Same generation but an outdated provider/model/dimensions: replace
        # the stored vector in place so incompatible vectors are never mixed.
        existing.embedding = vector
        existing.provider = result.provider
        existing.model = result.model
        existing.dimensions = settings.embedding_dimensions
    else:
        db.add(
            AgentEmbeddingVersion(
                agent_id=agent_id,
                embedding=vector,
                provider=result.provider,
                model=result.model,
                dimensions=settings.embedding_dimensions,
                generation=generation,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        # Duplicate delivery for the same generation: another worker won.
        db.rollback()
        return EmbeddingOutcome(agent_id, generation, stored=False, reason="already_embedded")
    return EmbeddingOutcome(agent_id, generation, stored=True, reason=None)


def backfill_agent_embeddings(db: Session, *, limit: int = 500) -> int:
    """Idempotently embed every agent whose current generation lacks a matching
    vector (or whose stored vector uses an outdated provider/model/dimensions).

    Returns the number of agents whose embedding was ensured (freshly stored or
    already current by a concurrent run). Safe to re-run.
    """
    statement = (
        select(Agent.id, Agent.embedding_generation)
        .outerjoin(
            AgentEmbeddingVersion,
            (AgentEmbeddingVersion.agent_id == Agent.id)
            & (AgentEmbeddingVersion.generation == Agent.embedding_generation),
        )
        .where(
            Agent.interest_manifesto.isnot(None),
            func.length(func.trim(Agent.interest_manifesto)) > 0,
            (
                AgentEmbeddingVersion.id.is_(None)
                | (AgentEmbeddingVersion.provider != settings.embedding_provider)
                | (AgentEmbeddingVersion.model != settings.embedding_model)
                | (AgentEmbeddingVersion.dimensions != settings.embedding_dimensions)
            ),
        )
        .limit(limit)
    )
    rows = db.execute(statement).all()
    attempts = 0
    for agent_id, generation in rows:
        outcome = embed_manifesto(db, agent_id=agent_id, generation=generation)
        if outcome.stored or outcome.reason == "already_embedded":
            attempts += 1
    return attempts
