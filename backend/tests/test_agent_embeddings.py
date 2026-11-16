"""Versioned agent interest-manifesto embedding service tests."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.agents.models import Agent
from app.modules.agents.service import register_agent, update_agent, update_manifesto
from app.modules.embeddings import service as embedding_service
from app.modules.embeddings.provider import EmbeddingProviderError, EmbeddingResult
from app.modules.organizations.models import Organization
from app.modules.routing.models import AgentEmbeddingVersion


def _organization(db: Session, slug: str = "embedding-test") -> Organization:
    organization = Organization(name="Embedding Test", slug=slug)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


def _agent(db: Session, organization: Organization, manifesto: str | None) -> Agent:
    return register_agent(
        db,
        organization_id=organization.id,
        company_name="Embedding Bot",
        industry_category=None,
        interest_manifesto=manifesto,
    )


class _FakeProvider:
    """Deterministic stand-in for the OpenAI adapter (no network)."""

    name = "openai"

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.calls = 0

    def embed(self, text: str) -> EmbeddingResult:
        self.calls += 1
        if self._fail:
            raise EmbeddingProviderError("The embedding provider request failed.")
        return EmbeddingResult(
            provider=self.name,
            model=settings.embedding_model,
            vector=[0.01] * settings.embedding_dimensions,
        )


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: _FakeProvider) -> None:
    monkeypatch.setattr(embedding_service, "get_embedding_provider", lambda: provider)


def _versions(db: Session, agent_id: UUID) -> list[AgentEmbeddingVersion]:
    return list(
        db.scalars(
            select(AgentEmbeddingVersion)
            .where(AgentEmbeddingVersion.agent_id == agent_id)
            .order_by(AgentEmbeddingVersion.generation)
        ).all()
    )


def test_manifesto_embedding_is_versioned_and_persisted(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = _organization(db)
    agent = _agent(db, organization, "We buy industrial robotics.")
    _use_provider(monkeypatch, _FakeProvider())

    outcome = embedding_service.embed_manifesto(
        db, agent_id=agent.id, generation=agent.embedding_generation
    )

    assert outcome.stored is True
    rows = _versions(db, agent.id)
    assert len(rows) == 1
    assert rows[0].generation == 1
    assert rows[0].provider == "openai"
    assert rows[0].model == settings.embedding_model
    assert rows[0].dimensions == settings.embedding_dimensions


def test_empty_manifesto_is_skipped(db: Session) -> None:
    organization = _organization(db)
    agent = _agent(db, organization, None)

    outcome = embedding_service.embed_manifesto(db, agent_id=agent.id, generation=1)

    assert outcome.stored is False
    assert outcome.reason == "empty_manifesto"
    assert _versions(db, agent.id) == []


def test_stale_generation_write_is_rejected(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    organization = _organization(db)
    agent = _agent(db, organization, "Original interests.")
    _use_provider(monkeypatch, _FakeProvider())

    first = embedding_service.embed_manifesto(db, agent_id=agent.id, generation=1)
    assert first.stored is True

    # The manifesto changes while a slow task for generation 1 is in flight.
    update_manifesto(
        db,
        agent_id=agent.id,
        organization_id=organization.id,
        interest_manifesto="Completely different interests.",
    )
    stale = embedding_service.embed_manifesto(db, agent_id=agent.id, generation=1)
    assert stale.stored is False
    assert stale.reason == "stale_generation"

    fresh = embedding_service.embed_manifesto(db, agent_id=agent.id, generation=2)
    assert fresh.stored is True

    rows = _versions(db, agent.id)
    assert [row.generation for row in rows] == [1, 2]


def test_duplicate_delivery_is_idempotent(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    organization = _organization(db)
    agent = _agent(db, organization, "Logistics optimization.")
    _use_provider(monkeypatch, _FakeProvider())

    first = embedding_service.embed_manifesto(db, agent_id=agent.id, generation=1)
    second = embedding_service.embed_manifesto(db, agent_id=agent.id, generation=1)

    assert first.stored is True
    assert second.stored is False
    assert second.reason == "already_embedded"
    assert len(_versions(db, agent.id)) == 1


def test_provider_failure_is_recorded_without_raising(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = _organization(db)
    agent = _agent(db, organization, "Renewable energy procurement.")
    _use_provider(monkeypatch, _FakeProvider(fail=True))

    outcome = embedding_service.embed_manifesto(db, agent_id=agent.id, generation=1)

    assert outcome.stored is False
    assert outcome.reason == "provider_unavailable"
    assert _versions(db, agent.id) == []


def test_manifesto_changes_bump_the_generation(db: Session) -> None:
    organization = _organization(db)
    agent = _agent(db, organization, "Original interests.")
    assert agent.embedding_generation == 1

    unchanged = update_manifesto(
        db,
        agent_id=agent.id,
        organization_id=organization.id,
        interest_manifesto="Original interests.",
    )
    assert unchanged.embedding_generation == 1

    changed = update_manifesto(
        db,
        agent_id=agent.id,
        organization_id=organization.id,
        interest_manifesto="New interests.",
    )
    assert changed.embedding_generation == 2

    via_patch = update_agent(
        db,
        agent_id=agent.id,
        organization_id=organization.id,
        company_name=None,
        industry_category=None,
        interest_manifesto="Third interests.",
    )
    assert via_patch.embedding_generation == 3


def test_backfill_is_idempotent_and_skips_current_embeddings(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = _organization(db)
    missing = _agent(db, organization, "Needs an embedding.")
    _agent(db, organization, None)  # no manifesto: never embedded
    outdated = _agent(db, organization, "Stored with an old model.")
    current = _agent(db, organization, "Already current.")

    # Outdated row for the current generation (model change without a
    # manifesto change) and a fully current row.
    db.add(
        AgentEmbeddingVersion(
            agent_id=outdated.id,
            embedding=[0.5] * settings.embedding_dimensions,
            provider="openai",
            model="old-model",
            dimensions=settings.embedding_dimensions,
            generation=outdated.embedding_generation,
        )
    )
    db.add(
        AgentEmbeddingVersion(
            agent_id=current.id,
            embedding=[0.25] * settings.embedding_dimensions,
            provider="openai",
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            generation=current.embedding_generation,
        )
    )
    db.commit()
    _use_provider(monkeypatch, _FakeProvider())

    first_run = embedding_service.backfill_agent_embeddings(db)
    assert first_run == 2  # missing + outdated; empty and current skipped

    second_run = embedding_service.backfill_agent_embeddings(db)
    assert second_run == 0

    assert len(_versions(db, missing.id)) == 1
    assert [row.model for row in _versions(db, outdated.id)] == [settings.embedding_model]
    assert len(_versions(db, current.id)) == 1


def test_worker_task_reports_stored_outcome(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    sqlite_session_factory,
) -> None:
    from unittest.mock import patch

    from app.workers.agent_tasks import embed_manifesto as embed_manifesto_task

    organization = _organization(db)
    agent = _agent(db, organization, "Warehouse automation.")
    _use_provider(monkeypatch, _FakeProvider())

    with patch("app.workers.agent_tasks.SessionLocal", sqlite_session_factory):
        result = embed_manifesto_task(str(agent.id), agent.embedding_generation)

    assert result["stored"] == "true"
    assert result["reason"] == ""
    assert len(_versions(db, agent.id)) == 1
