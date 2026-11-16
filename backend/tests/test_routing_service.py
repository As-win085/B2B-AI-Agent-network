"""Routing engine tests: the approved eight-step sequence.

Unit tests run on SQLite, where vector retrieval uses the Python cosine
fallback with the same SQL eligibility predicates as the pgvector path.
"""

from __future__ import annotations

import math
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.agents.models import Agent, AgentStatus
from app.modules.agents.service import register_agent
from app.modules.organizations.models import Organization
from app.modules.posts.models import Post, PostStatus
from app.modules.routing import service
from app.modules.routing.models import (
    AgentBlock,
    AgentEmbeddingVersion,
    RerankStatus,
    RoutingDecision,
    RoutingLog,
)
from app.modules.routing.reranker import RerankerError, RerankResult

# Short vectors keep the tests readable; cosine math is dimension-agnostic.
POST_VECTOR = [1.0, 0.0]
HIGH_A = [1.0, 0.1]  # cos ~0.995
HIGH_B = [1.0, 0.2]  # cos ~0.981
EXTERNAL = [1.0, 0.3]  # cos ~0.958
LOW = [0.0, 1.0]  # cos 0.0
IDENTICAL = [1.0, 0.0]  # cos 1.0


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm


def _organization(db: Session, slug: str, name: str) -> Organization:
    organization = Organization(name=name, slug=slug)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


def _agent(
    db: Session,
    organization: Organization,
    *,
    name: str,
    status: AgentStatus = AgentStatus.ACTIVE,
    manifesto: str | None = "interests",
) -> Agent:
    agent = register_agent(
        db,
        organization_id=organization.id,
        company_name=name,
        industry_category=None,
        interest_manifesto=manifesto,
    )
    if status is not AgentStatus.ACTIVE:
        agent.status = status.value
        db.commit()
        db.refresh(agent)
    return agent


def _version(
    db: Session,
    agent: Agent,
    vector: list[float],
    *,
    model: str = "test-model",
    generation: int | None = None,
) -> AgentEmbeddingVersion:
    version = AgentEmbeddingVersion(
        agent_id=agent.id,
        embedding=vector,
        provider="openai",
        model=model,
        dimensions=len(vector),
        generation=agent.embedding_generation if generation is None else generation,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def _post(
    db: Session,
    organization: Organization,
    author: Agent,
    *,
    vector: list[float] | None = POST_VECTOR,
    model: str = "test-model",
    status: PostStatus = PostStatus.PUBLISHED,
) -> Post:
    post = Post(
        organization_id=organization.id,
        author_agent_id=author.id,
        title="Routing fixture post",
        content="Content used for semantic routing.",
        status=status.value,
        embedding=vector,
        embedding_provider="openai" if vector is not None else None,
        embedding_model=model if vector is not None else None,
        embedding_generation=1,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def _logs(db: Session, post_id: UUID) -> list[RoutingLog]:
    return list(
        db.scalars(
            select(RoutingLog).where(RoutingLog.post_id == post_id).order_by(RoutingLog.rank)
        ).all()
    )


def _log_count(db: Session, post_id: UUID) -> int:
    return (
        db.scalar(select(func.count()).select_from(RoutingLog).where(RoutingLog.post_id == post_id))
        or 0
    )


class _FakeReranker:
    name = "cohere"
    model = "rerank-test"

    def __init__(self, *, scores: list[float] | None = None, fail: bool = False) -> None:
        self._scores = scores
        self._fail = fail

    def rerank(self, *, query: str, documents: list[str]) -> RerankResult:
        if self._fail:
            raise RerankerError("The reranker provider request failed.")
        assert self._scores is not None
        assert len(self._scores) == len(documents)
        return RerankResult(provider=self.name, model=self.model, scores=list(self._scores))


@pytest.fixture()
def routing_scenario(db: Session) -> dict[str, object]:
    """One publisher, eligible/ineligible candidates and a cross-org pool."""
    org_a = _organization(db, "org-a", "Org A")
    org_b = _organization(db, "org-b", "Org B")

    publisher = _agent(db, org_a, name="Publisher")
    suspended = _agent(db, org_a, name="Suspended", status=AgentStatus.SUSPENDED)
    blocked = _agent(db, org_a, name="Blocked")
    without_embedding = _agent(db, org_a, name="No Embedding")
    low = _agent(db, org_a, name="Low")
    high_a = _agent(db, org_a, name="High A")
    high_b = _agent(db, org_a, name="High B")
    external = _agent(db, org_b, name="External")

    # Steps 1–3 fixtures: publisher, suspended and blocked candidates would
    # otherwise be top-ranked (identical/high-similarity vectors).
    _version(db, publisher, IDENTICAL)
    _version(db, suspended, IDENTICAL)
    _version(db, blocked, IDENTICAL)
    _version(db, low, LOW)
    _version(db, high_a, HIGH_A)
    _version(db, high_b, HIGH_B)
    _version(db, external, EXTERNAL)

    db.add(
        AgentBlock(
            organization_id=org_a.id,
            blocked_agent_id=blocked.id,
            reason="policy",
        )
    )
    db.commit()

    post = _post(db, org_a, publisher)
    return {
        "db": db,
        "org_a": org_a,
        "org_b": org_b,
        "publisher": publisher,
        "suspended": suspended,
        "blocked": blocked,
        "without_embedding": without_embedding,
        "low": low,
        "high_a": high_a,
        "high_b": high_b,
        "external": external,
        "post": post,
    }


def test_eligibility_statement_applies_steps_one_to_three_in_sql(
    routing_scenario: dict[str, object],
) -> None:
    db = routing_scenario["db"]
    post = routing_scenario["post"]

    eligible = set(db.scalars(service._eligibility_statement(post)).all())

    # Publishing agent, suspended agent and blocked agent are excluded by the
    # SQL statement itself, before any vector retrieval happens.
    assert eligible == {
        routing_scenario["without_embedding"].id,
        routing_scenario["low"].id,
        routing_scenario["high_a"].id,
        routing_scenario["high_b"].id,
        routing_scenario["external"].id,
    }


def test_eight_step_sequence_persists_explainable_decisions(
    routing_scenario: dict[str, object],
) -> None:
    db = routing_scenario["db"]
    post = routing_scenario["post"]
    org_a = routing_scenario["org_a"]

    outcome = service.route_post(db, post_id=post.id)

    assert outcome.routed is True
    assert outcome.selected == 3
    assert outcome.candidates == 4  # low, high_a, high_b, external
    assert outcome.rerank_status == RerankStatus.SKIPPED_UNCONFIGURED.value

    logs = _logs(db, post.id)
    by_agent = {log.agent_id: log for log in logs}

    # Ineligible agents never enter the vector stage: no log rows at all.
    for excluded in (
        routing_scenario["publisher"],
        routing_scenario["suspended"],
        routing_scenario["blocked"],
        routing_scenario["without_embedding"],
    ):
        assert excluded.id not in by_agent

    # Selected recipients in similarity order, with ranks.
    selected = sorted(
        (log for log in logs if log.decision == RoutingDecision.SELECTED.value),
        key=lambda log: log.rank,
    )
    assert [log.agent_id for log in selected] == [
        routing_scenario["high_a"].id,
        routing_scenario["high_b"].id,
        routing_scenario["external"].id,
    ]
    assert [log.rank for log in selected] == [1, 2, 3]

    # Rejected candidate below the threshold is explained.
    low_log = by_agent[routing_scenario["low"].id]
    assert low_log.decision == RoutingDecision.REJECTED.value
    assert low_log.decision_reason == "below_threshold"
    assert low_log.rank is None

    # Every log is explainable and carries embedding/rerank metadata.
    for log in logs:
        assert log.organization_id == org_a.id  # post's tenant owns the decision
        assert math.isclose(
            log.similarity_score,
            _cosine(
                POST_VECTOR,
                {
                    routing_scenario["low"].id: LOW,
                    routing_scenario["high_a"].id: HIGH_A,
                    routing_scenario["high_b"].id: HIGH_B,
                    routing_scenario["external"].id: EXTERNAL,
                }[log.agent_id],
            ),
            rel_tol=1e-6,
        )
        assert log.rerank_score is None
        assert log.reranker_provider is None
        assert log.reranker_model is None
        assert log.rerank_status == RerankStatus.SKIPPED_UNCONFIGURED.value
        assert log.embedding_provider == "openai"
        assert log.embedding_model == "test-model"
        assert log.embedding_generation == 1
        assert log.decision_reason in {"meets_threshold", "below_threshold"}


def test_block_policy_is_tenant_scoped_to_the_posting_organization(
    routing_scenario: dict[str, object],
) -> None:
    db = routing_scenario["db"]
    org_b = routing_scenario["org_b"]
    external_author = _agent(db, org_b, name="Org B Publisher")
    _version(db, external_author, IDENTICAL)
    other_post = _post(db, org_b, external_author)

    service.route_post(db, post_id=other_post.id)

    agent_ids = {log.agent_id for log in _logs(db, other_post.id)}
    # Org A's block applies only to org A's posts: the blocked agent is a
    # normal candidate for org B's post.
    assert routing_scenario["blocked"].id in agent_ids
    assert routing_scenario["external"].id in agent_ids  # own-org candidate


def test_top_k_cutoff_bounds_the_candidate_stage(
    routing_scenario: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = routing_scenario["db"]
    post = routing_scenario["post"]
    monkeypatch.setattr(settings, "routing_top_k", 2)

    outcome = service.route_post(db, post_id=post.id)

    logs = _logs(db, post.id)
    assert outcome.candidates == 2
    # The two highest-similarity candidates only (publisher excluded).
    assert {log.agent_id for log in logs} == {
        routing_scenario["high_a"].id,
        routing_scenario["high_b"].id,
    }
    # Third-ranked agent is absent entirely: it never reached the logs.
    assert routing_scenario["external"].id not in {log.agent_id for log in logs}


def test_recipient_limit_rejects_candidates_above_threshold(
    routing_scenario: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = routing_scenario["db"]
    post = routing_scenario["post"]
    monkeypatch.setattr(settings, "routing_max_recipients", 2)

    outcome = service.route_post(db, post_id=post.id)

    assert outcome.selected == 2
    logs = _logs(db, post.id)
    by_agent = {log.agent_id: log for log in logs}
    external = by_agent[routing_scenario["external"].id]
    assert external.decision == RoutingDecision.REJECTED.value
    assert external.decision_reason == "recipient_limit_exceeded"
    assert external.rank is None


def test_threshold_boundary_is_inclusive(
    routing_scenario: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = routing_scenario["db"]
    org_a = routing_scenario["org_a"]
    publisher = routing_scenario["publisher"]

    # A dedicated candidate whose cosine similarity we can compute exactly
    # with the same formula the engine uses.
    boundary_vector = [1.0, 1.0]
    boundary_agent = _agent(db, org_a, name="Boundary Candidate")
    _version(db, boundary_agent, boundary_vector)
    boundary = _cosine(POST_VECTOR, boundary_vector)

    # At the exact boundary the candidate is selected (>= is inclusive).
    monkeypatch.setattr(settings, "routing_score_threshold", boundary)
    at_boundary = _post(db, org_a, publisher)
    service.route_post(db, post_id=at_boundary.id)
    log_at = next(log for log in _logs(db, at_boundary.id) if log.agent_id == boundary_agent.id)
    assert log_at.decision == RoutingDecision.SELECTED.value

    # Just above the boundary the same candidate is rejected.
    monkeypatch.setattr(settings, "routing_score_threshold", boundary + 1e-12)
    above_boundary = _post(db, org_a, publisher)
    service.route_post(db, post_id=above_boundary.id)
    log_above = next(
        log for log in _logs(db, above_boundary.id) if log.agent_id == boundary_agent.id
    )
    assert log_above.decision == RoutingDecision.REJECTED.value
    assert log_above.decision_reason == "below_threshold"


def test_reranking_completed_reorders_and_is_recorded(
    routing_scenario: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = routing_scenario["db"]
    post = routing_scenario["post"]
    # Documents arrive in similarity order [high_a, high_b, external, low];
    # the reranker inverts that order so the low-similarity candidate wins.
    fake = _FakeReranker(scores=[0.30, 0.20, 0.10, 0.95])
    monkeypatch.setattr(service, "get_reranker", lambda: fake)

    outcome = service.route_post(db, post_id=post.id)

    assert outcome.rerank_status == RerankStatus.COMPLETED.value
    logs = _logs(db, post.id)
    by_agent = {log.agent_id: log for log in logs}

    low_log = by_agent[routing_scenario["low"].id]
    assert low_log.decision == RoutingDecision.SELECTED.value
    assert low_log.rank == 1
    assert low_log.rerank_score == pytest.approx(0.95)

    high_a_log = by_agent[routing_scenario["high_a"].id]
    assert high_a_log.decision == RoutingDecision.REJECTED.value
    assert high_a_log.decision_reason == "below_threshold"
    assert high_a_log.rerank_score == pytest.approx(0.30)

    # Scores and provider/model are recorded on every row.
    for log in logs:
        assert log.rerank_status == RerankStatus.COMPLETED.value
        assert log.reranker_provider == "cohere"
        assert log.reranker_model == "rerank-test"


def test_reranker_failure_degrades_to_similarity_order(
    routing_scenario: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = routing_scenario["db"]
    post = routing_scenario["post"]
    fake = _FakeReranker(fail=True)
    monkeypatch.setattr(service, "get_reranker", lambda: fake)

    outcome = service.route_post(db, post_id=post.id)

    assert outcome.rerank_status == RerankStatus.FAILED.value
    logs = _logs(db, post.id)
    selected = [
        log.agent_id
        for log in sorted(
            (log for log in logs if log.decision == RoutingDecision.SELECTED.value),
            key=lambda log: log.rank,
        )
    ]
    # Similarity order preserved despite the reranker outage.
    assert selected == [
        routing_scenario["high_a"].id,
        routing_scenario["high_b"].id,
        routing_scenario["external"].id,
    ]
    for log in logs:
        assert log.rerank_status == RerankStatus.FAILED.value
        assert log.rerank_score is None
        assert log.reranker_provider == "cohere"  # attempted provider recorded


def test_routing_is_idempotent_per_post(
    routing_scenario: dict[str, object],
) -> None:
    db = routing_scenario["db"]
    post = routing_scenario["post"]

    first = service.route_post(db, post_id=post.id)
    count_after_first = _log_count(db, post.id)
    second = service.route_post(db, post_id=post.id)

    assert first.routed is True
    assert second.routed is False
    assert second.reason == "already_routed"
    assert _log_count(db, post.id) == count_after_first


def test_unroutable_posts_are_skipped_with_reasons(
    routing_scenario: dict[str, object],
) -> None:
    db = routing_scenario["db"]
    org_a = routing_scenario["org_a"]
    publisher = routing_scenario["publisher"]

    processing = _post(db, org_a, publisher, status=PostStatus.PROCESSING)
    no_embedding = _post(db, org_a, publisher, vector=None)

    assert service.route_post(db, post_id=processing.id).reason == "post_not_published"
    assert service.route_post(db, post_id=no_embedding.id).reason == "post_embedding_missing"
    assert service.route_post(db, post_id=UUID(int=0)).reason == "post_not_found"
    assert _log_count(db, processing.id) == 0
    assert _log_count(db, no_embedding.id) == 0


def test_incompatible_models_and_stale_generations_are_excluded(
    routing_scenario: dict[str, object],
) -> None:
    db = routing_scenario["db"]
    org_a = routing_scenario["org_a"]
    publisher = routing_scenario["publisher"]

    wrong_model_agent = _agent(db, org_a, name="Wrong Model")
    _version(db, wrong_model_agent, IDENTICAL, model="other-model")
    stale_agent = _agent(db, org_a, name="Stale Generation")
    _version(db, stale_agent, IDENTICAL, generation=stale_agent.embedding_generation + 1)

    post = _post(db, org_a, publisher)
    service.route_post(db, post_id=post.id)

    agent_ids = {log.agent_id for log in _logs(db, post.id)}
    assert wrong_model_agent.id not in agent_ids
    assert stale_agent.id not in agent_ids


def test_route_post_worker_task_executes_engine(
    routing_scenario: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    sqlite_session_factory,
) -> None:
    from unittest.mock import patch

    from app.workers.routing_tasks import route_post as route_post_task

    db = routing_scenario["db"]
    post = routing_scenario["post"]

    with patch("app.workers.routing_tasks.SessionLocal", sqlite_session_factory):
        result = route_post_task(str(post.id))

    assert result["routed"] == "true"
    assert result["selected"] == "3"
    assert result["rerank_status"] == RerankStatus.SKIPPED_UNCONFIGURED.value
    assert _log_count(db, post.id) == 4


def test_post_edit_voids_stale_routing_decisions(
    routing_scenario: dict[str, object],
) -> None:
    db = routing_scenario["db"]
    post = routing_scenario["post"]
    publisher = routing_scenario["publisher"]

    service.route_post(db, post_id=post.id)
    assert _log_count(db, post.id) == 4

    from app.modules.posts import service as posts_service

    posts_service.update_post_by_author(
        db,
        post_id=post.id,
        agent=publisher,
        fields={"content": "Edited content that changes the meaning."},
    )
    # Decisions referenced the previous content generation and are void.
    assert _log_count(db, post.id) == 0

    # Re-publish and route the edited content fresh.
    post = db.get(Post, post.id)
    post.status = PostStatus.PUBLISHED.value
    post.embedding = POST_VECTOR
    post.embedding_provider = "openai"
    post.embedding_model = "test-model"
    db.commit()

    outcome = service.route_post(db, post_id=post.id)
    assert outcome.routed is True
    assert _log_count(db, post.id) == 4
