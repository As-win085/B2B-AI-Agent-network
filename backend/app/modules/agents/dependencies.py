"""Agent authentication dependency.

Machine-to-machine requests authenticate with an ``Authorization: Bearer asa_...``
header carrying the raw agent API key. This is completely separate from the
human JWT system in ``app.modules.auth.dependencies``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import DbSession
from app.core.exceptions import AppError
from app.modules.agents.models import Agent
from app.modules.agents.service import authenticate_agent

_agent_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="AgentBearerAuth",
    description="Agent API key returned by POST /api/v1/agents/{id}/credentials.",
)


def get_agent_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_agent_bearer)],
    db: DbSession,
) -> Agent:
    """Validate an agent API key and return the authenticated Agent row."""
    if credentials is None:
        raise AppError(
            "Agent authentication required.",
            code="unauthenticated",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authenticate_agent(db, raw_credential=credentials.credentials)


AgentPrincipalDep = Annotated[Agent, Depends(get_agent_principal)]
