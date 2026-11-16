"""pgvector retrieval and routing against live PostgreSQL.

Skipped unless ``RUN_INTEGRATION_TESTS=1``. Exercises the real ``<=>`` cosine
operator and the HNSW index on ``agent_embedding_versions`` — the code path
unit tests cannot reach on SQLite. Each test creates uniquely named tenants
and removes them again, so the shared database stays clean.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, text

import app.models  # noqa: F401 - register all mappers before configuring
from app.core.database import SessionLocal, engine
from app.modules.agents.models import Agent
from app.modules.organizations.models import Organization
from app.modules.posts.models import Post, PostStatus
from app.modules.routing import service
from app.modules.routing.models import AgentEmbeddingVersion, RoutingLog

pytestmark = pytest.mark.integration

_DIMENSIONS = 1536  # settings.embedding_dimensions


def _suffix() -> str:
    return uuid.uuid4().hex[:12]


def _vector(head: float, tail: float) -> list[float]:
    """Deterministic 1536-dim unit-friendly vector with a controllable angle."""
    return [head, tail] + [0.0] * (_DIMENSIONS - 2)


def test_pgvector_retrieval_and_routing_against_postgres() -> None:
    suffix = _suffix()
    try:
        with SessionLocal() as db:
            organization = Organization(name=f"Pgvec {suffix}", slug=f"pgvec-{suffix}")
            db.add(organization)
            db.commit()
            db.refresh(organization)

            def add_agent(company_name: str) -> Agent:
                agent = Agent(
                    organization_id=organization.id,
                    company_name=f"{company_name} {suffix}",
                    interest_manifesto="interests",
                    embedding_generation=1,
                )
                db.add(agent)
                db.commit()
                db.refresh(agent)
                return agent

            publisher = add_agent("Publisher")
            high = add_agent("High")
            low = add_agent("Low")

            post = Post(
                organization_id=organization.id,
                author_agent_id=publisher.id,
                title="pgvector routing post",
                content="Semantic content for the pgvector path.",
                status=PostStatus.PUBLISHED.value,
                embedding=_vector(1.0, 0.0),
                embedding_provider="openai",
                embedding_model="test-model",
                embedding_generation=1,
            )
            db.add(post)
            db.commit()
            db.refresh(post)

            # Cosine(post, high) ~= 0.9987, cosine(post, low) ~= 0.8944.
            for agent, vector in ((high, _vector(1.0, 0.05)), (low, _vector(1.0, 0.5))):
                db.add(
                    AgentEmbeddingVersion(
                        agent_id=agent.id,
                        embedding=vector,
                        provider="openai",
                        model="test-model",
                        dimensions=_DIMENSIONS,
                        generation=1,
                    )
                )
            db.commit()

            # Keep the reranker out of this test: settings come from the real
            # .env in integration mode and must not trigger provider calls.
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(service, "get_reranker", lambda: None)

                outcome = service.route_post(db, post_id=post.id)

            assert outcome.routed is True
            assert outcome.selected == 2

            logs = list(
                db.scalars(
                    select(RoutingLog)
                    .where(RoutingLog.post_id == post.id)
                    .order_by(RoutingLog.rank)
                ).all()
            )
            assert [log.agent_id for log in logs] == [high.id, low.id]
            assert [log.rank for log in logs] == [1, 2]
            assert all(log.decision == "selected" for log in logs)
            assert all(0.75 <= log.similarity_score <= 1.0 for log in logs), (
                "pgvector cosine distances must convert to sane similarities"
            )
            # The pgvector branch (dialect == postgresql) was exercised: the
            # similarity of the top candidate must reflect the ``<=>`` order.
            assert logs[0].similarity_score > logs[1].similarity_score
            assert all(log.rerank_status == "skipped_unconfigured" for log in logs)

            # HNSW index exists on the live database for this table.
            with engine.connect() as connection:
                index_names = (
                    connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE tablename = 'agent_embedding_versions'"
                        )
                    )
                    .scalars()
                    .all()
                )
            assert "ix_agent_embedding_versions_embedding_hnsw" in index_names
    finally:
        # Organization cascade removes agents, posts, embedding versions and
        # routing logs (all tenant/agent FKs are ON DELETE CASCADE).
        with engine.begin() as connection:
            connection.execute(delete(Organization).where(Organization.slug.like(f"%{suffix}%")))
            remaining = connection.execute(
                text("SELECT count(*) FROM organizations WHERE slug LIKE :pattern"),
                {"pattern": f"%{suffix}%"},
            ).scalar_one()
        assert remaining == 0, "integration fixture must not leave data behind"
