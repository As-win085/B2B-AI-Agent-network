"""Post records and post-embedding lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.shared.models import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class PostStatus(StrEnum):
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"


_POST_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in PostStatus)
_EMBEDDING_TYPE = Vector(settings.embedding_dimensions).with_variant(JSON(), "sqlite")


class Post(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """A business post owned by an organization and authored by an agent."""

    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_POST_STATUS_VALUES})",
            name="post_status_valid",
        ),
        Index("ix_posts_author_agent_id", "author_agent_id"),
        Index("ix_posts_status", "status"),
        Index(
            "ix_posts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    author_agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'processing'")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(_EMBEDDING_TYPE, nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
