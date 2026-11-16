"""Eight-step semantic routing engine.

Approved plan sequence:

1. Exclude the publishing agent.
2. Select eligible and active agents through SQL.
3. Exclude blocked agents and policy-ineligible candidates.
4. Retrieve the top-K candidates using vector similarity.
5. Rerank the candidates.
6. Apply the configured threshold.
7. Select eligible recipients within the recipient limit.
8. Save routing decisions (transactionally, explainably).

Steps 1–3 form one SQL eligibility query that completes *before* vector
retrieval: ineligible agents never enter the candidate stage. Retrieval uses
pgvector cosine distance ordered by an HNSW index on PostgreSQL; unit tests run
on SQLite, where the same filters are applied and cosine similarity is
computed in Python.

The candidate pool is cross-organization by design (approved plan): every
ACTIVE agent of any tenant is a candidate except the publisher, policy
blocks and (by construction) agents without a current embedding.
``routing_logs.organization_id`` is always the posting organization.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Float, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.modules.agents.models import Agent, AgentStatus
from app.modules.posts.models import Post, PostStatus
from app.modules.routing.models import (
    AgentBlock,
    AgentEmbeddingVersion,
    RerankStatus,
    RoutingDecision,
    RoutingLog,
)
from app.modules.routing.reranker import get_reranker
from app.shared.tenancy import TenantScopedRepository

logger = logging.getLogger(__name__)

_REASON_MEETS_THRESHOLD = "meets_threshold"
_REASON_BELOW_THRESHOLD = "below_threshold"
_REASON_RECIPIENT_LIMIT = "recipient_limit_exceeded"


@dataclass(frozen=True, slots=True)
class RoutingOutcome:
    """Summary of one routing run (safe to log and return to Celery)."""

    post_id: UUID
    routed: bool
    reason: str | None = None
    candidates: int = 0
    selected: int = 0
    rerank_status: str | None = None


@dataclass(frozen=True, slots=True)
class _Candidate:
    agent: Agent
    version: AgentEmbeddingVersion
    similarity: float


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        norm_left += a * a
        norm_right += b * b
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_left) * math.sqrt(norm_right))


def _eligibility_statement(post: Post):
    """Steps 1–3 as a single SQL statement.

    Returns a SELECT of eligible agent IDs: active agents only (2), excluding
    the publisher (1) and any agent this organization has blocked (3).
    """
    blocked = select(AgentBlock.blocked_agent_id).where(
        AgentBlock.organization_id == post.organization_id
    )
    return select(Agent.id).where(
        Agent.status == AgentStatus.ACTIVE.value,
        Agent.id != post.author_agent_id,
        Agent.id.not_in(blocked),
    )


def _retrieval_predicate(post: Post):
    """Vector-stage filters shared by the pgvector and Python paths.

    Only current-generation embeddings compatible with the post's embedding
    (same provider, model and dimensions) participate, so vectors from
    incompatible embedding models are never mixed.
    """
    assert post.embedding is not None
    return (
        Agent.id.in_(_eligibility_statement(post)),
        AgentEmbeddingVersion.generation == Agent.embedding_generation,
        AgentEmbeddingVersion.provider == post.embedding_provider,
        AgentEmbeddingVersion.model == post.embedding_model,
        AgentEmbeddingVersion.dimensions == len(post.embedding),
    )


def _retrieve_candidates(db: Session, post: Post, top_k: int) -> list[_Candidate]:
    """Step 4: bounded top-K vector similarity retrieval."""
    bind = db.get_bind()
    predicate = _retrieval_predicate(post)

    if bind.dialect.name == "postgresql":
        # The ``<=>`` operator inherits the Vector result type from its left
        # operand; cast to Float so the float distance is not parsed as a
        # vector string.
        distance = AgentEmbeddingVersion.embedding.op("<=>")(post.embedding).cast(Float)
        statement = (
            select(AgentEmbeddingVersion, Agent, distance.label("distance"))
            .join(Agent, Agent.id == AgentEmbeddingVersion.agent_id)
            .where(*predicate)
            .order_by(distance)
            .limit(top_k)
        )
        candidates = [
            _Candidate(agent=agent, version=version, similarity=1.0 - float(raw_distance))
            for version, agent, raw_distance in db.execute(statement).all()
        ]
        # Deterministic tie-breaking for equal distances.
        candidates.sort(key=lambda c: (-c.similarity, str(c.agent.id)))
        return candidates[:top_k]

    # SQLite/test path: same predicates, cosine computed in Python.
    statement = (
        select(AgentEmbeddingVersion, Agent)
        .join(Agent, Agent.id == AgentEmbeddingVersion.agent_id)
        .where(*predicate)
    )
    candidates = [
        _Candidate(
            agent=agent,
            version=version,
            similarity=_cosine_similarity(post.embedding, version.embedding),
        )
        for version, agent in db.execute(statement).all()
    ]
    candidates.sort(key=lambda c: (-c.similarity, str(c.agent.id)))
    return candidates[:top_k]


def _rerank(
    post: Post, candidates: list[_Candidate]
) -> tuple[str, dict[UUID, float], str | None, str | None]:
    """Step 5: rerank when configured, otherwise degrade to similarity order.

    Returns ``(rerank_status, scores_by_agent, provider, model)``. A failure
    never blocks routing; it is recorded as ``failed`` in every log row.
    """
    if not candidates:
        return RerankStatus.SKIPPED_UNCONFIGURED.value, {}, None, None

    reranker = get_reranker()
    if reranker is None:
        return RerankStatus.SKIPPED_UNCONFIGURED.value, {}, None, None

    provider = reranker.name
    model = reranker.model
    documents = [(candidate.agent.interest_manifesto or "").strip() for candidate in candidates]
    try:
        result = reranker.rerank(query=f"{post.title}\n\n{post.content}", documents=documents)
        scores = {
            candidate.agent.id: score
            for candidate, score in zip(candidates, result.scores, strict=True)
        }
    except Exception:  # noqa: BLE001 - reranker outages must not break routing
        logger.warning(
            "Reranking failed; degrading to similarity ordering",
            extra={"post_id": str(post.id), "reranker": provider},
        )
        return RerankStatus.FAILED.value, {}, provider, model
    return RerankStatus.COMPLETED.value, scores, provider, model


def route_post(db: Session, *, post_id: UUID) -> RoutingOutcome:
    """Execute the eight-step routing sequence for one published post.

    All decisions are persisted in a single transaction. Re-running for the
    same post is a no-op (``already_routed``), which makes duplicate event
    deliveries and concurrent workers idempotent.
    """
    post = db.get(Post, post_id)
    if post is None:
        return RoutingOutcome(post_id, routed=False, reason="post_not_found")
    if post.status != PostStatus.PUBLISHED.value:
        return RoutingOutcome(post_id, routed=False, reason="post_not_published")
    if post.embedding is None or not post.embedding_provider or not post.embedding_model:
        return RoutingOutcome(post_id, routed=False, reason="post_embedding_missing")
    post_generation = post.embedding_generation

    existing = db.scalar(
        select(func.count()).select_from(RoutingLog).where(RoutingLog.post_id == post_id)
    )
    if existing:
        return RoutingOutcome(post_id, routed=False, reason="already_routed")

    # Steps 1–3 (eligibility SQL) complete before step 4 (vector retrieval).
    candidates = _retrieve_candidates(db, post, settings.routing_top_k)
    if not candidates:
        return RoutingOutcome(post_id, routed=True, candidates=0, selected=0)

    # Step 5.
    rerank_status, rerank_scores, reranker_provider, reranker_model = _rerank(post, candidates)

    # Steps 6–7: threshold on the final score (rerank score when reranking
    # completed, otherwise vector similarity), then the recipient limit.
    threshold = settings.routing_score_threshold

    def final_score(candidate: _Candidate) -> float:
        if rerank_status == RerankStatus.COMPLETED.value:
            return rerank_scores[candidate.agent.id]
        return candidate.similarity

    ordered = sorted(
        candidates,
        key=lambda c: (-final_score(c), -c.similarity, str(c.agent.id)),
    )
    selected = [c for c in ordered if final_score(c) >= threshold][
        : settings.routing_max_recipients
    ]
    selected_ids = {candidate.agent.id for candidate in selected}

    # Step 8: transactional, explainable persistence of every decision.
    logs: list[RoutingLog] = []
    for position, candidate in enumerate(selected, start=1):
        logs.append(
            _build_log(
                post,
                candidate,
                decision=RoutingDecision.SELECTED,
                reason=_REASON_MEETS_THRESHOLD,
                rank=position,
                rerank_status=rerank_status,
                rerank_scores=rerank_scores,
                reranker_provider=reranker_provider,
                reranker_model=reranker_model,
            )
        )
    for candidate in ordered:
        if candidate.agent.id in selected_ids:
            continue
        reason = (
            _REASON_RECIPIENT_LIMIT
            if final_score(candidate) >= threshold
            else _REASON_BELOW_THRESHOLD
        )
        logs.append(
            _build_log(
                post,
                candidate,
                decision=RoutingDecision.REJECTED,
                reason=reason,
                rank=None,
                rerank_status=rerank_status,
                rerank_scores=rerank_scores,
                reranker_provider=reranker_provider,
                reranker_model=reranker_model,
            )
        )

    # Serialize against a concurrent re-edit before writing: lock the post
    # row for the rest of this transaction. An author's edit either waits
    # here and then voids these logs, or it has already committed — in which
    # case routing the superseded content aborts instead of leaving stale
    # decisions that would block re-routing after re-publish.
    current = db.execute(
        select(Post.status, Post.embedding_generation).where(Post.id == post_id).with_for_update()
    ).first()
    if current is None or current[0] != PostStatus.PUBLISHED.value or current[1] != post_generation:
        db.rollback()
        return RoutingOutcome(post_id, routed=False, reason="post_editing")

    db.add_all(logs)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent run for the same post won the unique (post_id, agent_id)
        # constraint: treat as already routed instead of duplicating decisions.
        db.rollback()
        return RoutingOutcome(post_id, routed=False, reason="already_routed")

    return RoutingOutcome(
        post_id,
        routed=True,
        candidates=len(logs),
        selected=len(selected),
        rerank_status=rerank_status,
    )


def _build_log(
    post: Post,
    candidate: _Candidate,
    *,
    decision: RoutingDecision,
    reason: str,
    rank: int | None,
    rerank_status: str,
    rerank_scores: dict[UUID, float],
    reranker_provider: str | None,
    reranker_model: str | None,
) -> RoutingLog:
    """FR-15: one explainable audit row with embedding/rerank metadata."""
    return RoutingLog(
        organization_id=post.organization_id,
        post_id=post.id,
        agent_id=candidate.agent.id,
        similarity_score=candidate.similarity,
        rerank_score=rerank_scores.get(candidate.agent.id),
        rank=rank,
        decision=decision.value,
        decision_reason=reason,
        embedding_provider=candidate.version.provider,
        embedding_model=candidate.version.model,
        embedding_generation=candidate.version.generation,
        reranker_provider=reranker_provider,
        reranker_model=reranker_model,
        rerank_status=rerank_status,
    )


# ---------------------------------------------------------------------------
# Tenant-scoped reads
# ---------------------------------------------------------------------------


def _require_post(db: Session, *, post_id: UUID, organization_id: UUID) -> Post:
    post = db.scalar(
        select(Post).where(Post.id == post_id, Post.organization_id == organization_id)
    )
    if post is None:
        raise AppError("Post not found.", code="not_found", status_code=404)
    return post


def _require_agent(db: Session, *, agent_id: UUID, organization_id: UUID) -> Agent:
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id)
    )
    if agent is None:
        raise AppError("Agent not found.", code="not_found", status_code=404)
    return agent


def list_post_routing_logs(
    db: Session,
    *,
    post_id: UUID,
    organization_id: UUID,
    page: int,
    page_size: int,
) -> tuple[list[RoutingLog], int]:
    """Routing decisions for one post owned by the caller's organization."""
    _require_post(db, post_id=post_id, organization_id=organization_id)
    repository = TenantScopedRepository(db, RoutingLog, organization_id)
    statement = repository.statement().where(RoutingLog.post_id == post_id)
    total = (
        db.scalar(
            select(func.count())
            .select_from(RoutingLog)
            .where(
                RoutingLog.organization_id == organization_id,
                RoutingLog.post_id == post_id,
            )
        )
        or 0
    )
    logs = list(
        db.scalars(
            statement.order_by(RoutingLog.created_at.desc(), RoutingLog.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return logs, total


def list_agent_routing_logs(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
    page: int,
    page_size: int,
) -> tuple[list[RoutingLog], int]:
    """Routing activity recorded about an agent of the caller's organization.

    The tenant predicate is applied through the join on ``agents`` so it holds
    even if this function is reused without the ownership pre-check: only logs
    whose candidate agent belongs to the caller's tenant are returned, while
    logs generated by other tenants' posts stay visible (they are decisions
    *about* this agent and are needed for the recipient's dashboard).
    """
    _require_agent(db, agent_id=agent_id, organization_id=organization_id)
    statement = (
        select(RoutingLog)
        .join(Agent, Agent.id == RoutingLog.agent_id)
        .where(
            Agent.organization_id == organization_id,
            RoutingLog.agent_id == agent_id,
        )
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(RoutingLog)
            .join(Agent, Agent.id == RoutingLog.agent_id)
            .where(
                Agent.organization_id == organization_id,
                RoutingLog.agent_id == agent_id,
            )
        )
        or 0
    )
    logs = list(
        db.scalars(
            statement.order_by(RoutingLog.created_at.desc(), RoutingLog.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return logs, total


# ---------------------------------------------------------------------------
# Blocking policy (agent_blocks)
# ---------------------------------------------------------------------------


def list_agent_blocks(db: Session, *, organization_id: UUID) -> list[AgentBlock]:
    repository = TenantScopedRepository(db, AgentBlock, organization_id)
    return list(
        db.scalars(repository.statement().order_by(AgentBlock.created_at, AgentBlock.id)).all()
    )


def block_agent(
    db: Session,
    *,
    organization_id: UUID,
    blocked_agent_id: UUID,
    reason: str | None,
) -> AgentBlock:
    """Block an agent (of any tenant) from receiving this tenant's posts.

    The blocked agent is intentionally *not* looked up through the caller's
    tenant: cross-organization blocking is the point of this policy table.
    Existence is still validated so foreign keys stay honest.
    """
    agent_exists = db.scalar(select(Agent.id).where(Agent.id == blocked_agent_id))
    if agent_exists is None:
        raise AppError("Agent not found.", code="not_found", status_code=404)

    existing = db.scalar(
        select(AgentBlock).where(
            AgentBlock.organization_id == organization_id,
            AgentBlock.blocked_agent_id == blocked_agent_id,
        )
    )
    if existing is not None:
        raise AppError("Agent is already blocked.", code="already_blocked", status_code=409)

    block = AgentBlock(
        organization_id=organization_id,
        blocked_agent_id=blocked_agent_id,
        reason=reason,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def unblock_agent(db: Session, *, organization_id: UUID, blocked_agent_id: UUID) -> AgentBlock:
    """Remove a block and return the deleted row for the API response."""
    block = db.scalar(
        select(AgentBlock).where(
            AgentBlock.organization_id == organization_id,
            AgentBlock.blocked_agent_id == blocked_agent_id,
        )
    )
    if block is None:
        raise AppError("Block not found.", code="not_found", status_code=404)
    snapshot = AgentBlock(
        id=block.id,
        organization_id=block.organization_id,
        blocked_agent_id=block.blocked_agent_id,
        reason=block.reason,
        created_at=block.created_at,
        updated_at=block.updated_at,
    )
    db.delete(block)
    db.commit()
    return snapshot
