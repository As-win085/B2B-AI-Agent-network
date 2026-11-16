"""Agent identity, credentials and webhook configuration.

Two tables:

* ``agents``            -- one row per AI agent owned by an organization.
* ``agent_credentials`` -- machine-to-machine API keys (stored as hashes).

Human JWT tokens and agent API keys are completely separate credential systems.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.models import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    pass


class AgentStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


_AGENT_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in AgentStatus)


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """An AI agent owned by an organization."""

    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_AGENT_STATUS_VALUES})",
            name="agent_status_valid",
        ),
        Index("ix_agents_status", "status"),
    )

    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interest_manifesto: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Webhook signing secret stored encrypted (Fernet). Null until configured.
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'active'"),
    )
    # Bumped whenever the interest manifesto changes so a slow embedding task
    # can never overwrite the embedding of a newer generation.
    embedding_generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )

    credentials: Mapped[list[AgentCredential]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )


class AgentCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One issued API credential for an agent.

    The raw secret is shown exactly once at creation and never stored.
    ``credential_hash`` is a SHA-256 hex digest used for lookup.
    ``credential_prefix`` is the first 8 characters of the raw key,
    stored in plaintext so operators can identify which key is which.
    """

    __tablename__ = "agent_credentials"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credential_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    credential_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )

    agent: Mapped[Agent] = relationship(back_populates="credentials")
