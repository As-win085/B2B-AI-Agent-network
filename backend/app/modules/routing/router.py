"""Organization-scoped routing activity and blocking policy API.

There is deliberately no endpoint that triggers routing: routing runs in the
``routing.route_post`` background task (Phase 6 enqueues it from the
``post.published`` event).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.core.dependencies import DbSession
from app.core.responses import ApiResponse, success
from app.modules.auth.dependencies import OrganizationContextDep, require_roles
from app.modules.routing import service
from app.modules.routing.schemas import (
    AgentBlockRequest,
    AgentBlockResponse,
    RoutingLogResponse,
)

router = APIRouter(tags=["routing"])
_ADMIN_DEP = require_roles("owner", "admin")


@router.get(
    "/posts/{post_id}/routing-logs",
    response_model=ApiResponse[list[RoutingLogResponse]],
)
def get_post_routing_logs(
    post_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Explainable routing decisions for one of the organization's posts."""
    logs, total = service.list_post_routing_logs(
        db,
        post_id=post_id,
        organization_id=ctx.organization.id,
        page=page,
        page_size=page_size,
    )
    return success(
        [RoutingLogResponse.model_validate(log) for log in logs],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/agents/{agent_id}/routing-logs",
    response_model=ApiResponse[list[RoutingLogResponse]],
)
def get_agent_routing_logs(
    agent_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Routing activity recorded about one of the organization's agents."""
    logs, total = service.list_agent_routing_logs(
        db,
        agent_id=agent_id,
        organization_id=ctx.organization.id,
        page=page,
        page_size=page_size,
    )
    return success(
        [RoutingLogResponse.model_validate(log) for log in logs],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/agent-blocks", response_model=ApiResponse[list[AgentBlockResponse]])
def list_agent_blocks(ctx: OrganizationContextDep, db: DbSession) -> dict:
    """List the agents this organization blocks from receiving its posts."""
    _ADMIN_DEP(ctx)
    blocks = service.list_agent_blocks(db, organization_id=ctx.organization.id)
    return success([AgentBlockResponse.model_validate(block) for block in blocks])


@router.post(
    "/agent-blocks",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[AgentBlockResponse],
)
def create_agent_block(
    payload: AgentBlockRequest,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Block any agent (including one owned by another organization)."""
    _ADMIN_DEP(ctx)
    block = service.block_agent(
        db,
        organization_id=ctx.organization.id,
        blocked_agent_id=payload.blocked_agent_id,
        reason=payload.reason,
    )
    return success(AgentBlockResponse.model_validate(block))


@router.delete(
    "/agent-blocks/{blocked_agent_id}",
    response_model=ApiResponse[AgentBlockResponse],
)
def delete_agent_block(
    blocked_agent_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Remove a block previously created by this organization."""
    _ADMIN_DEP(ctx)
    block = service.unblock_agent(
        db,
        organization_id=ctx.organization.id,
        blocked_agent_id=blocked_agent_id,
    )
    return success(AgentBlockResponse.model_validate(block))
