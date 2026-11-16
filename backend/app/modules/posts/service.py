"""Tenant-scoped post lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.events.outbox import POST_PUBLISHED, record_event
from app.modules.agents.models import Agent
from app.modules.posts.models import Post, PostStatus
from app.modules.routing.models import RoutingLog
from app.shared.tenancy import TenantScopedRepository


def _repository(db: Session, organization_id: UUID) -> TenantScopedRepository[Post]:
    return TenantScopedRepository(db, Post, organization_id)


def _require_post(db: Session, *, post_id: UUID, organization_id: UUID) -> Post:
    post = _repository(db, organization_id).get(post_id)
    if post is None:
        raise AppError("Post not found.", code="not_found", status_code=404)
    return post


def create_post(
    db: Session,
    *,
    agent: Agent,
    title: str,
    content: str,
    expires_at: datetime | None,
) -> Post:
    """Persist a processing post, deriving both author and tenant from auth."""
    post = Post(
        organization_id=agent.organization_id,
        author_agent_id=agent.id,
        title=title,
        content=content,
        expires_at=expires_at,
        status=PostStatus.PROCESSING.value,
        embedding_generation=1,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def fail_embedding_enqueue(db: Session, *, post_id: UUID, generation: int) -> Post | None:
    post = db.get(Post, post_id)
    if post is None or post.embedding_generation != generation:
        return post
    post.status = PostStatus.FAILED.value
    post.failure_code = "embedding_queue_unavailable"
    post.embedding = None
    db.commit()
    db.refresh(post)
    return post


def update_post_by_author(
    db: Session,
    *,
    post_id: UUID,
    agent: Agent,
    fields: dict[str, object],
) -> tuple[Post, bool]:
    """Update the authenticated author's post; re-embed only changed text."""
    post = _require_post(db, post_id=post_id, organization_id=agent.organization_id)
    if post.author_agent_id != agent.id:
        raise AppError("Post not found.", code="not_found", status_code=404)
    if post.status == PostStatus.ARCHIVED:
        raise AppError("Archived posts cannot be edited.", code="post_archived", status_code=409)

    text_changed = False
    if "title" in fields and fields["title"] != post.title:
        post.title = str(fields["title"])
        text_changed = True
    if "content" in fields and fields["content"] != post.content:
        post.content = str(fields["content"])
        text_changed = True
    if "expires_at" in fields:
        post.expires_at = fields["expires_at"]  # type: ignore[assignment]

    if post.status == PostStatus.FAILED and ("title" in fields or "content" in fields):
        # Re-submitting an unchanged body is a supported retry after a transient
        # embedding failure.
        text_changed = True

    if text_changed:
        post.embedding_generation += 1
        post.embedding = None
        post.embedding_provider = None
        post.embedding_model = None
        post.published_at = None
        post.failure_code = None
        post.status = PostStatus.PROCESSING.value
        # Routing decisions referenced the previous content generation and are
        # void: clearing them keeps the (post_id, agent_id) uniqueness rule
        # intact so the next publish routes the edited content fresh.
        db.execute(delete(RoutingLog).where(RoutingLog.post_id == post_id))
        # Webhook deliveries are voided with them: stale-content notifications
        # must not survive to collide with the fresh routing after re-publish
        # (unique post+recipient) or contradict it in delivery history.
        from app.modules.webhooks.service import void_post_deliveries

        void_post_deliveries(db, post_id=post_id)

    db.commit()
    db.refresh(post)
    return post, text_changed


def archive_post(db: Session, *, post_id: UUID, organization_id: UUID) -> Post:
    post = _require_post(db, post_id=post_id, organization_id=organization_id)
    if post.status == PostStatus.ARCHIVED:
        return post
    post.status = PostStatus.ARCHIVED.value
    post.archived_at = datetime.now(UTC)
    post.embedding = None
    post.embedding_provider = None
    post.embedding_model = None
    db.commit()
    db.refresh(post)
    return post


def list_posts(
    db: Session,
    *,
    organization_id: UUID,
    page: int,
    page_size: int,
    status_filter: str | None,
) -> tuple[list[Post], int]:
    repository = _repository(db, organization_id)
    statement = repository.statement()
    count_statement = (
        select(func.count())
        .select_from(Post)
        .where(Post.organization_id == repository.organization_id)
    )
    now = datetime.now(UTC)
    if status_filter == "expired":
        predicate = (Post.status == PostStatus.PUBLISHED.value) & (Post.expires_at <= now)
        statement = statement.where(predicate)
        count_statement = count_statement.where(predicate)
    elif status_filter == "published":
        predicate = (Post.status == PostStatus.PUBLISHED.value) & (
            (Post.expires_at.is_(None)) | (Post.expires_at > now)
        )
        statement = statement.where(predicate)
        count_statement = count_statement.where(predicate)
    elif status_filter is not None:
        statement = statement.where(Post.status == status_filter)
        count_statement = count_statement.where(Post.status == status_filter)

    total = db.scalar(count_statement) or 0
    posts = list(
        db.scalars(
            statement.order_by(Post.created_at.desc(), Post.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return posts, total


def get_post(db: Session, *, post_id: UUID, organization_id: UUID) -> Post:
    return _require_post(db, post_id=post_id, organization_id=organization_id)


def get_processing_snapshot(
    db: Session, *, post_id: UUID, generation: int
) -> tuple[str, str] | None:
    post = db.get(Post, post_id)
    if (
        post is None
        or post.embedding_generation != generation
        or post.status != PostStatus.PROCESSING
    ):
        return None
    return post.title, post.content


def finish_embedding(
    db: Session,
    *,
    post_id: UUID,
    generation: int,
    vector: list[float],
    provider: str,
    model: str,
) -> bool:
    post = db.get(Post, post_id)
    if (
        post is None
        or post.embedding_generation != generation
        or post.status != PostStatus.PROCESSING
    ):
        return False
    post.embedding = vector
    post.embedding_provider = provider
    post.embedding_model = model
    post.failure_code = None
    post.status = PostStatus.PUBLISHED.value
    post.published_at = datetime.now(UTC)
    # Transactional outbox: the event row commits atomically with the status
    # change, so a published post can never exist without its event.
    record_event(
        db,
        aggregate_type="post",
        aggregate_id=post.id,
        event_type=POST_PUBLISHED,
        payload={
            "post_id": str(post.id),
            "organization_id": str(post.organization_id),
            "author_agent_id": str(post.author_agent_id),
            "embedding_generation": post.embedding_generation,
        },
    )
    db.commit()
    return True


def fail_embedding(db: Session, *, post_id: UUID, generation: int, failure_code: str) -> bool:
    post = db.get(Post, post_id)
    if (
        post is None
        or post.embedding_generation != generation
        or post.status != PostStatus.PROCESSING
    ):
        return False
    post.embedding = None
    post.embedding_provider = None
    post.embedding_model = None
    post.published_at = None
    post.failure_code = failure_code
    post.status = PostStatus.FAILED.value
    db.commit()
    return True
