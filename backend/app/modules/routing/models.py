"""Routing decision records, agent embedding versions and blocking policy.

Three tables:

* ``agent_embedding_versions`` -- versioned interest-manifesto embeddings.
* ``routing_logs``             -- explainable per-candidate routing decisions.
* ``agent_blocks``             -- organization blocks against an agent.

``routing_logs.organization_id`` is the *posting* organization: routing is
cross-organization, so a log row is tenant-owned by the post's tenant while
the candidate ``agent_id`` may belong to another tenant.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.shared.models import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

_EMBEDDING_TYPE = Vector(settings.embedding_dimensions).with_variant(JSON(), "sqlite")


class RoutingDecision(StrEnum):
    """Final decision for one candidate agent on one post."""

    SELECTED = "selected"
    REJECTED = "rejected"


class RerankStatus(StrEnum):
    """Whether reranking contributed to this routing run."""

    COMPLETED = "completed"
    SKIPPED_UNCONFIGURED = "skipped_unconfigured"
    FAILED = "failed"


_ROUTING_DECISION_VALUES = ", ".join(f"'{d.value}'" for d in RoutingDecision)
_RERANK_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in RerankStatus)


class AgentEmbeddingVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One immutable interest-manifesto embedding for an agent generation."""

    __tablename__ = "agent_embedding_versions"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "generation",
            name="uq_agent_embedding_versions_agent_id_generation",
        ),
        Index(
            "ix_agent_embedding_versions_agent_id_generation",
            "agent_id",
            "generation",
        ),
        Index(
            "ix_agent_embedding_versions_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(_EMBEDDING_TYPE, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)


class RoutingLog(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """Explainable routing decision for one (post, candidate) pair."""

    __tablename__ = "routing_logs"
    __table_args__ = (
        UniqueConstraint("post_id", "agent_id", name="uq_routing_logs_post_id_agent_id"),
        CheckConstraint(
            f"decision IN ({_ROUTING_DECISION_VALUES})",
            name="routing_log_decision_valid",
        ),
        CheckConstraint(
            f"rerank_status IN ({_RERANK_STATUS_VALUES})",
            name="routing_log_rerank_status_valid",
        ),
        CheckConstraint("rank IS NULL OR rank >= 1", name="routing_log_rank_valid"),
        Index(
            "ix_routing_logs_post_org_created",
            "post_id",
            "organization_id",
            "created_at",
            "id",
        ),
        Index("ix_routing_logs_agent_created", "agent_id", "created_at", "id"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    similarity_score: Mapped[float] = mapped_column(nullable=False)
    rerank_score: Mapped[float | None] = mapped_column(nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_reason: Mapped[str] = mapped_column(String(80), nullable=False)
    # Embedding version of the *candidate agent* used for this comparison.
    embedding_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    reranker_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reranker_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rerank_status: Mapped[str] = mapped_column(String(30), nullable=False)


class AgentBlock(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """An organization blocks an agent from receiving its routed posts."""

    __tablename__ = "agent_blocks"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "blocked_agent_id",
            name="uq_agent_blocks_organization_id_blocked_agent_id",
        ),
        Index("ix_agent_blocks_blocked_agent_id", "blocked_agent_id"),
    )

    blocked_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# Re-export for convenient imports (created_at comes from TimestampMixin).
__all__ = [
    "AgentBlock",
    "AgentEmbeddingVersion",
    "RerankStatus",
    "RoutingDecision",
    "RoutingLog",
]
