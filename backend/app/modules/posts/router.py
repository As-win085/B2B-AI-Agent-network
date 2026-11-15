"""Post publishing and organization-scoped management API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.core.dependencies import DbSession
from app.core.exceptions import AppError
from app.core.responses import ApiResponse, success
from app.modules.agents.dependencies import AgentPrincipalDep
from app.modules.auth.dependencies import OrganizationContextDep, require_roles
from app.modules.posts import service
from app.modules.posts.schemas import CreatePostRequest, PostResponse, UpdatePostRequest
from app.workers.post_tasks import embed_and_publish

router = APIRouter(prefix="/posts", tags=["posts"])
_ADMIN_DEP = require_roles("owner", "admin")


def _queue(db, post, generation: int) -> None:
    try:
        embed_and_publish.delay(str(post.id), generation)
    except Exception:
        service.fail_embedding_enqueue(db, post_id=post.id, generation=generation)
        raise AppError(
            "Post processing is temporarily unavailable.",
            code="embedding_queue_unavailable",
            status_code=503,
        ) from None


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=ApiResponse[PostResponse])
def create_post(payload: CreatePostRequest, agent: AgentPrincipalDep, db: DbSession) -> dict:
    post = service.create_post(
        db,
        agent=agent,
        title=payload.title,
        content=payload.content,
        expires_at=payload.expires_at,
    )
    _queue(db, post, post.embedding_generation)
    return success(PostResponse.from_post(post))


@router.get("", response_model=ApiResponse[list[PostResponse]])
def list_posts(
    ctx: OrganizationContextDep,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
) -> dict:
    allowed = {"processing", "published", "failed", "archived", "expired"}
    if status_filter is not None and status_filter not in allowed:
        raise AppError("Unsupported post status.", code="validation_error", status_code=422)
    posts, total = service.list_posts(
        db,
        organization_id=ctx.organization.id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )
    return success(
        [PostResponse.from_post(post) for post in posts],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/{post_id}", response_model=ApiResponse[PostResponse])
def get_post(post_id: UUID, ctx: OrganizationContextDep, db: DbSession) -> dict:
    post = service.get_post(db, post_id=post_id, organization_id=ctx.organization.id)
    return success(PostResponse.from_post(post))


@router.patch(
    "/{post_id}", status_code=status.HTTP_202_ACCEPTED, response_model=ApiResponse[PostResponse]
)
def update_post(
    post_id: UUID,
    payload: UpdatePostRequest,
    agent: AgentPrincipalDep,
    db: DbSession,
) -> dict:
    post, text_changed = service.update_post_by_author(
        db,
        post_id=post_id,
        agent=agent,
        fields=payload.model_dump(exclude_unset=True),
    )
    if text_changed:
        _queue(db, post, post.embedding_generation)
    return success(PostResponse.from_post(post))


@router.delete("/{post_id}", response_model=ApiResponse[PostResponse])
def archive_post(
    post_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    _ADMIN_DEP(ctx)
    post = service.archive_post(db, post_id=post_id, organization_id=ctx.organization.id)
    return success(PostResponse.from_post(post))
