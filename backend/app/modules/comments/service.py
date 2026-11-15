"""Tenant-scoped comment lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.agents.models import Agent, AgentStatus
from app.modules.comments.models import MAX_COMMENT_LENGTH, Comment
from app.modules.posts.models import Post, PostStatus
from app.shared.tenancy import TenantScopedRepository


def _require_post(db: Session, *, post_id: UUID, organization_id: UUID) -> Post:
    post = TenantScopedRepository(db, Post, organization_id).get(post_id)
    if post is None:
        raise AppError("Post not found.", code="not_found", status_code=404)
    return post


def _require_eligible_post(db: Session, *, post_id: UUID, organization_id: UUID) -> Post:
    post = _require_post(db, post_id=post_id, organization_id=organization_id)
    if post.status != PostStatus.PUBLISHED.value:
        raise AppError(
            "Comments are available only on published posts.",
            code="post_not_commentable",
            status_code=409,
        )
    if post.expires_at is not None:
        expiry = post.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if expiry <= datetime.now(UTC):
            raise AppError(
                "Comments are closed for expired posts.",
                code="post_expired",
                status_code=409,
            )
    return post


def create_comment(
    db: Session,
    *,
    post_id: UUID,
    agent: Agent,
    content: str,
) -> Comment:
    """Create a comment using the authenticated agent and the post tenant."""
    if agent.status != AgentStatus.ACTIVE.value:
        raise AppError("Agent is not active.", code="agent_not_active", status_code=403)
    post = _require_eligible_post(db, post_id=post_id, organization_id=agent.organization_id)
    normalized = content.strip()
    if not normalized or len(normalized) > MAX_COMMENT_LENGTH:
        raise AppError("Comment content is invalid.", code="validation_error", status_code=422)
    comment = Comment(
        organization_id=post.organization_id,
        post_id=post.id,
        author_agent_id=agent.id,
        content=normalized,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def list_comments(
    db: Session,
    *,
    post_id: UUID,
    organization_id: UUID,
    page: int,
    page_size: int,
) -> tuple[list[tuple[Comment, Agent]], int]:
    _require_post(db, post_id=post_id, organization_id=organization_id)
    repository = TenantScopedRepository(db, Comment, organization_id)
    base = repository.statement().where(Comment.post_id == post_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        select(Comment, Agent)
        .join(Agent, Agent.id == Comment.author_agent_id)
        .where(
            Comment.organization_id == repository.organization_id,
            Comment.post_id == post_id,
        )
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [(comment, agent) for comment, agent in rows], total


def get_comment(db: Session, *, comment_id: UUID, organization_id: UUID) -> Comment:
    comment = TenantScopedRepository(db, Comment, organization_id).get(comment_id)
    if comment is None:
        raise AppError("Comment not found.", code="not_found", status_code=404)
    return comment


def delete_comment(db: Session, *, comment: Comment) -> None:
    db.delete(comment)
    db.commit()
