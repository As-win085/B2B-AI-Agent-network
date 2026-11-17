"""Resolve a comments API caller as either an agent or a human member."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import DbSession
from app.core.exceptions import AppError
from app.modules.agents.models import Agent
from app.modules.agents.service import authenticate_agent
from app.modules.auth.dependencies import (
    OrganizationContext,
    get_organization_context,
    get_principal,
)

_bearer = HTTPBearer(auto_error=False, scheme_name="CommentsBearerAuth")


@dataclass(frozen=True, slots=True)
class CommentActor:
    organization_id: UUID
    agent: Agent | None = None
    role: str | None = None


def get_comment_actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> CommentActor:
    if credentials is None:
        raise AppError(
            "Authentication required.",
            code="unauthenticated",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials.startswith("asa_"):
        agent = authenticate_agent(db, raw_credential=credentials.credentials)
        return CommentActor(organization_id=agent.organization_id, agent=agent)

    principal = get_principal(credentials=credentials, db=db)
    context: OrganizationContext = get_organization_context(principal=principal)
    return CommentActor(
        organization_id=context.organization.id,
        role=context.role,
    )


CommentActorDep = Annotated[CommentActor, Depends(get_comment_actor)]
