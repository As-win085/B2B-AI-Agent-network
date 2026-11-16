"""Agent management endpoints.

All human-facing routes use OrganizationContextDep and require owner/admin.
The agent-authentication dependency (AgentPrincipalDep) is separate and used
only for machine-to-machine endpoints in later phases.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, status

from app.core.dependencies import DbSession
from app.core.responses import ApiResponse, success
from app.modules.agents import service
from app.modules.agents.dependencies import AgentPrincipalDep
from app.modules.agents.models import Agent
from app.modules.agents.schemas import (
    AgentResponse,
    AgentStatusAction,
    CredentialResponse,
    IssueCredentialRequest,
    IssuedCredentialResponse,
    RegisterAgentRequest,
    UpdateAgentRequest,
    UpdateManifestoRequest,
    WebhookConfigRequest,
    WebhookConfigResponse,
)
from app.modules.auth.dependencies import OrganizationContextDep, require_roles
from app.workers.agent_tasks import embed_manifesto

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

# Only owners and admins may manage agents.
_ADMIN_DEP = require_roles("owner", "admin")


def _queue_manifesto_embedding(agent: Agent) -> None:
    """Best-effort enqueue of the versioned manifesto embedding task.

    Unlike post publication, a queue outage must not fail agent management:
    the idempotent backfill (:func:`app.modules.embeddings.service.
    backfill_agent_embeddings`) picks up anything missed here.
    """
    if not (agent.interest_manifesto or "").strip():
        return
    try:
        embed_manifesto.delay(str(agent.id), agent.embedding_generation)
    except Exception:
        logger.warning(
            "Agent manifesto embedding enqueue failed",
            extra={"agent_id": str(agent.id), "generation": agent.embedding_generation},
        )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[AgentResponse],
)
def register_agent(
    payload: RegisterAgentRequest,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Register a new AI agent under the active organization."""
    _ADMIN_DEP(ctx)
    agent = service.register_agent(
        db,
        organization_id=ctx.organization.id,
        company_name=payload.company_name,
        industry_category=payload.industry_category,
        interest_manifesto=payload.interest_manifesto,
    )
    _queue_manifesto_embedding(agent)
    return success(AgentResponse.from_orm_agent(agent))


@router.get("", response_model=ApiResponse[list[AgentResponse]])
def list_agents(
    ctx: OrganizationContextDep,
    db: DbSession,
    status_filter: str | None = None,
) -> dict:
    """List all agents belonging to the active organization."""
    agents = service.list_agents(
        db,
        organization_id=ctx.organization.id,
        status=status_filter,
    )
    return success([AgentResponse.from_orm_agent(a) for a in agents])


@router.get("/me", response_model=ApiResponse[AgentResponse])
def get_authenticated_agent(agent: AgentPrincipalDep) -> dict:
    """Return the agent identity authenticated by its machine credential."""
    return success(AgentResponse.from_orm_agent(agent))


@router.get("/{agent_id}", response_model=ApiResponse[AgentResponse])
def get_agent(
    agent_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Retrieve a single agent by ID."""
    agent = service.get_agent(db, agent_id=agent_id, organization_id=ctx.organization.id)
    return success(AgentResponse.from_orm_agent(agent))


@router.patch("/{agent_id}", response_model=ApiResponse[AgentResponse])
def update_agent(
    agent_id: UUID,
    payload: UpdateAgentRequest,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Update agent profile fields."""
    _ADMIN_DEP(ctx)
    agent = service.update_agent(
        db,
        agent_id=agent_id,
        organization_id=ctx.organization.id,
        company_name=payload.company_name,
        industry_category=payload.industry_category,
        interest_manifesto=payload.interest_manifesto,
    )
    if payload.interest_manifesto is not None:
        _queue_manifesto_embedding(agent)
    return success(AgentResponse.from_orm_agent(agent))


@router.delete("/{agent_id}", response_model=ApiResponse[AgentResponse])
def deactivate_agent(
    agent_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Deactivate an agent and revoke all its credentials."""
    _ADMIN_DEP(ctx)
    agent = service.deactivate_agent(
        db,
        agent_id=agent_id,
        organization_id=ctx.organization.id,
    )
    return success(AgentResponse.from_orm_agent(agent))


@router.post("/{agent_id}/status", response_model=ApiResponse[AgentResponse])
def change_agent_status(
    agent_id: UUID,
    payload: AgentStatusAction,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Suspend or reactivate an agent."""
    _ADMIN_DEP(ctx)
    if payload.action == "suspend":
        agent = service.suspend_agent(db, agent_id=agent_id, organization_id=ctx.organization.id)
    elif payload.action == "reactivate":
        agent = service.reactivate_agent(db, agent_id=agent_id, organization_id=ctx.organization.id)
    else:
        agent = service.deactivate_agent(db, agent_id=agent_id, organization_id=ctx.organization.id)
    return success(AgentResponse.from_orm_agent(agent))


@router.patch("/{agent_id}/manifesto", response_model=ApiResponse[AgentResponse])
def update_manifesto(
    agent_id: UUID,
    payload: UpdateManifestoRequest,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Replace the agent's interest manifesto."""
    _ADMIN_DEP(ctx)
    agent = service.update_manifesto(
        db,
        agent_id=agent_id,
        organization_id=ctx.organization.id,
        interest_manifesto=payload.interest_manifesto,
    )
    _queue_manifesto_embedding(agent)
    return success(AgentResponse.from_orm_agent(agent))


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/credentials",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[IssuedCredentialResponse],
)
def issue_credential(
    agent_id: UUID,
    payload: IssueCredentialRequest,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Issue a new API credential. The secret is shown exactly once."""
    _ADMIN_DEP(ctx)
    cred, raw_secret = service.issue_credential(
        db,
        agent_id=agent_id,
        organization_id=ctx.organization.id,
        label=payload.label,
        expires_in_days=payload.expires_in_days,
        rotate=payload.rotate,
    )
    return success(
        {
            "credential": CredentialResponse.model_validate(cred),
            "secret": raw_secret,
        }
    )


@router.get(
    "/{agent_id}/credentials",
    response_model=ApiResponse[list[CredentialResponse]],
)
def list_credentials(
    agent_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """List credential metadata for an agent (no secrets)."""
    creds = service.list_credentials(
        db,
        agent_id=agent_id,
        organization_id=ctx.organization.id,
    )
    return success([CredentialResponse.model_validate(c) for c in creds])


@router.delete(
    "/{agent_id}/credentials/{credential_id}",
    response_model=ApiResponse[CredentialResponse],
)
def revoke_credential(
    agent_id: UUID,
    credential_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Revoke a credential immediately."""
    _ADMIN_DEP(ctx)
    cred = service.revoke_credential(
        db,
        agent_id=agent_id,
        organization_id=ctx.organization.id,
        credential_id=credential_id,
    )
    return success(CredentialResponse.model_validate(cred))


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


@router.put("/{agent_id}/webhook", response_model=ApiResponse[WebhookConfigResponse])
def configure_webhook(
    agent_id: UUID,
    payload: WebhookConfigRequest,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Configure the agent's webhook URL. Generates a signing secret if none exists."""
    _ADMIN_DEP(ctx)
    agent, plaintext_secret = service.configure_webhook(
        db,
        agent_id=agent_id,
        organization_id=ctx.organization.id,
        webhook_url=payload.webhook_url,
        rotate_secret=payload.rotate_secret,
    )
    return success(
        WebhookConfigResponse(
            webhook_url=agent.webhook_url,  # type: ignore[arg-type]
            webhook_configured=agent.webhook_secret_encrypted is not None,
            signing_secret=plaintext_secret,
        )
    )


@router.post("/{agent_id}/webhook/test", response_model=ApiResponse[dict])
def test_webhook(
    agent_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Check webhook URL syntax and SSRF policy without sending a request.

    Full async delivery is implemented in ASAMA-107.
    """
    _ADMIN_DEP(ctx)
    agent = service.get_agent(db, agent_id=agent_id, organization_id=ctx.organization.id)
    if not agent.webhook_url:
        from app.core.exceptions import AppError

        raise AppError(
            "No webhook URL configured for this agent.",
            code="webhook_not_configured",
            status_code=409,
        )
    from app.modules.agents.webhook import validate_webhook_url

    validate_webhook_url(agent.webhook_url)
    return success({"valid": True, "delivery_attempted": False, "url": agent.webhook_url})
