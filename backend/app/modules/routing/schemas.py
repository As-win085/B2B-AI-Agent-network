"""Routing, routing-log and agent-block API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RoutingLogResponse(BaseModel):
    """One explainable routing decision (FR-15)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    post_id: UUID
    agent_id: UUID
    organization_id: UUID
    similarity_score: float
    rerank_score: float | None
    rank: int | None
    decision: str
    decision_reason: str
    embedding_provider: str
    embedding_model: str
    embedding_generation: int
    reranker_provider: str | None
    reranker_model: str | None
    rerank_status: str
    created_at: datetime


class AgentBlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocked_agent_id: UUID
    reason: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional operator-facing reason for the block.",
    )


class AgentBlockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    blocked_agent_id: UUID
    reason: str | None
    created_at: datetime
