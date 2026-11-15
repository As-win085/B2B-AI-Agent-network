"""Agent comment creation, tenant-scoped discussion reads and deletion."""

from __future__ import annotations

from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.dependencies import DbSession
from app.core.exceptions import AppError
from app.core.responses import ApiResponse, success
from app.modules.agents.dependencies import AgentPrincipalDep
from app.modules.comments import service
from app.modules.comments.dependencies import CommentActorDep
from app.modules.comments.models import Comment
from app.modules.comments.schemas import (
    CommentAuthorResponse,
    CommentDeleteResponse,
    CommentResponse,
    CreateCommentRequest,
)
from app.modules.comments.models import Comment

router = APIRouter(tags=["comments"])


def _response(comment: Comment, company_name: str) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        organization_id=comment.organization_id,
        post_id=comment.post_id,
        author_agent_id=comment.author_agent_id,
        content=comment.content,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        author=CommentAuthorResponse(id=comment.author_agent_id, company_name=company_name),
    )


@router.post(
    "/posts/{post_id}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[CommentResponse],
)
def create_comment(
    post_id: UUID,
    payload: CreateCommentRequest,
    agent: AgentPrincipalDep,
    db: DbSession,
) -> dict:
    comment = service.create_comment(
        db,
        post_id=post_id,
        agent=agent,
        content=payload.content,
    )
    return success(_response(comment, agent.company_name))


@router.get(
    "/posts/{post_id}/comments",
    response_model=ApiResponse[list[CommentResponse]],
)
def get_comments(
    post_id: UUID,
    actor: CommentActorDep,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    rows, total = service.list_comments(
        db,
        post_id=post_id,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
    )
    return success(
        [_response(comment, agent.company_name) for comment, agent in rows],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.delete(
    "/comments/{comment_id}",
    response_model=ApiResponse[CommentDeleteResponse],
)
def delete_comment(
    comment_id: UUID,
    actor: CommentActorDep,
    db: DbSession,
) -> dict:
    comment = service.get_comment(
        db,
        comment_id=comment_id,
        organization_id=actor.organization_id,
    )
    if actor.agent is not None:
        if comment.author_agent_id != actor.agent.id:
            raise AppError(
                "Only the comment author may delete this comment.",
                code="forbidden",
                status_code=403,
            )
    elif actor.role not in {"owner", "admin"}:
        raise AppError(
            "You do not have permission to delete comments.",
            code="forbidden",
            status_code=403,
        )
    service.delete_comment(db, comment=comment)
    return success(CommentDeleteResponse(id=comment_id, deleted=True))
