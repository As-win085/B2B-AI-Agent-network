"""Agent management endpoints.

All human-facing routes use OrganizationContextDep and require owner/admin.
The agent-authentication dependency (AgentPrincipalDep) is separate and used
only for machine-to-machine endpoints in later phases.
"""

from __future__ import annotations

import json
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

router = APIRouter(prefix="/agents", tags=["agents"])

# Only owners and admins may manage agents.
_ADMIN_DEP = require_roles("owner", "admin")


def _queue_manifesto_embedding(agent: Agent) -> None:
    """Best-effort enqueue of the versioned manifesto embedding task.

    Unlike post publication, a queue outage must not fail agent management:
    the idempotent backfill (:func:`app.modules.embeddings.service.
    backfill_agent_embeddings`) picks up anything missed here.
    """
    import embed_manifesto

    embed_manifesto(agent.id)


@router.post("/{agent_id}/webhook/test", response_model=ApiResponse[dict])
def test_webhook(
    agent_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Send a real, signed test ping to the agent's configured webhook URL.

    Performs the full delivery pipeline (HMAC signing, SSRF validation, timeout,
    redirect safety) exactly as ordinary delivery does, so the test validates
    end-to-end behaviour without going through the retry / dead-letter machinery.

    The agent's webhook secret is never exposed in the API response or logs.
    The test payload is constructed from the agent's own registration data;
    the endpoint cannot be used as a network proxy for arbitrary URLs.
    """
    from app.core.exceptions import AppError
    from app.modules.agents.webhook import decrypt_webhook_secret, validate_webhook_url
    from app.modules.webhooks.service import _send
    from app.modules.webhooks.signing import compute_signature, delivery_headers

    _ADMIN_DEP(ctx)
    agent = service.get_agent(db, agent_id=agent_id, organization_id=ctx.organization.id)
    if not agent.webhook_url:
        raise AppError(
            "No webhook URL configured for this agent.",
            code="webhook_not_configured",
            status_code=409,
        )
    # --- resolvers use the agent's registered URL; no arbitrary submission ---
    url = agent.webhook_url

    # ---- SSRF + redirect validation at queue time (same as ordinary delivery) ---
    try:
        url = validate_webhook_url(url)
    except AppError as e:
        return error({"code": e.code, "message": e.detail}, status_code=e.status_code)

    # ---- decrypt the secret in-memory only -------------------------------
    secret = decrypt_webhook_secret(agent.webhook_secret_encrypted)

    # ---- build a test payload keyed to the agent's own registration ---------
    test_event_id = uuid4()
    test_payload = {
        "event_id": str(test_event_id),
        "event_type": "test.ping",
        "timestamp": datetime.now(UTC).isoformat(),
        "data": {
            "test": True,
            "agent_id": str(agent.id),
            "agent_name": agent.company_name,
        },
    }
    body = json.dumps(test_payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(int(datetime.now(UTC).timestamp() * 1000))  # epoch ms
    headers = delivery_headers(
        event_id=str(test_event_id),
        event_type="test.ping",
        timestamp=timestamp,
        signature=compute_signature(secret, timestamp=timestamp, body=body),
    )

    # ---- send with full protections (same _send path as ordinary delivery) ---
    try:
        response = _send(url, body, headers)
        outcome = "delivered" if (200 <= response.status_code < 300) else f"http_{response.status_code}"
        last_error = None
    except Exception as e:  # noqa: BLE001 - any unexpected transport error
        outcome = "failed"
        last_error = _safe_error(e)

    return success(
        {
            "valid": True,
            "delivery_attempted": True,
            "outcome": outcome,
            "response_status": (
                response.status_code if outcome == "delivered" else None
            ),
            "last_error": last_error,
            "url": url,
            "event_id": str(test_event_id),
        }
    )