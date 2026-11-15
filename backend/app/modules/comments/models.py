"""Comment persistence for agent conversations on posts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

MAX_COMMENT_LENGTH = 5_000


class Comment(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """A comment authored by an organization agent on an organization post."""

    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint(
            "length(trim(content)) > 0 AND length(content) <= 5000",
            name="comment_content_valid",
        ),
        Index(
            "ix_comments_post_org_created",
            "post_id",
            "organization_id",
            "created_at",
            "id",
        ),
        Index("ix_comments_author_agent_id", "author_agent_id"),
    )

    post_id: Mapped[UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    author_agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
