"""Agent management service.

All public functions receive an explicit ``organization_id`` so the service
layer never relies on the caller to add the tenant predicate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.agents.credentials import (
    credential_display_prefix,
    generate_agent_credential,
    hash_agent_credential,
)
from app.modules.agents.models import Agent, AgentCredential, AgentStatus
from app.modules.agents.webhook import (
    decrypt_webhook_secret,
    encrypt_webhook_secret,
    generate_webhook_secret,
    validate_webhook_url,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _require_agent(db: Session, agent_id: UUID, organization_id: UUID) -> Agent:
    """Load an agent that belongs to the given organization or raise 404."""
    agent = db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == organization_id,
        )
    )
    if agent is None:
        raise AppError("Agent not found.", code="not_found", status_code=404)
    return agent


def _require_active_agent(db: Session, agent_id: UUID, organization_id: UUID) -> Agent:
    agent = _require_agent(db, agent_id, organization_id)
    if agent.status != AgentStatus.ACTIVE:
        raise AppError(
            "Agent is not active.",
            code="agent_not_active",
            status_code=403,
        )
    return agent


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


def register_agent(
    db: Session,
    *,
    organization_id: UUID,
    company_name: str,
    industry_category: str | None,
    interest_manifesto: str | None,
) -> Agent:
    agent = Agent(
        organization_id=organization_id,
        company_name=company_name,
        industry_category=industry_category,
        interest_manifesto=interest_manifesto,
        status=AgentStatus.ACTIVE.value,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def list_agents(
    db: Session,
    *,
    organization_id: UUID,
    status: str | None = None,
) -> list[Agent]:
    stmt = select(Agent).where(Agent.organization_id == organization_id)
    if status is not None:
        stmt = stmt.where(Agent.status == status)
    stmt = stmt.order_by(Agent.created_at)
    return list(db.scalars(stmt).all())


def get_agent(db: Session, *, agent_id: UUID, organization_id: UUID) -> Agent:
    return _require_agent(db, agent_id, organization_id)


def update_agent(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
    company_name: str | None,
    industry_category: str | None,
    interest_manifesto: str | None,
) -> Agent:
    agent = _require_agent(db, agent_id, organization_id)
    if company_name is not None:
        agent.company_name = company_name
    if industry_category is not None:
        agent.industry_category = industry_category
    if interest_manifesto is not None:
        agent.interest_manifesto = interest_manifesto
    db.commit()
    db.refresh(agent)
    return agent


def update_manifesto(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
    interest_manifesto: str,
) -> Agent:
    agent = _require_agent(db, agent_id, organization_id)
    agent.interest_manifesto = interest_manifesto
    db.commit()
    db.refresh(agent)
    return agent


def suspend_agent(db: Session, *, agent_id: UUID, organization_id: UUID) -> Agent:
    agent = _require_agent(db, agent_id, organization_id)
    if agent.status == AgentStatus.DEACTIVATED:
        raise AppError(
            "A deactivated agent cannot be suspended.",
            code="agent_deactivated",
            status_code=409,
        )
    agent.status = AgentStatus.SUSPENDED.value
    db.commit()
    db.refresh(agent)
    return agent


def reactivate_agent(db: Session, *, agent_id: UUID, organization_id: UUID) -> Agent:
    agent = _require_agent(db, agent_id, organization_id)
    if agent.status == AgentStatus.DEACTIVATED:
        raise AppError(
            "A deactivated agent cannot be reactivated.",
            code="agent_deactivated",
            status_code=409,
        )
    agent.status = AgentStatus.ACTIVE.value
    db.commit()
    db.refresh(agent)
    return agent


def deactivate_agent(db: Session, *, agent_id: UUID, organization_id: UUID) -> Agent:
    agent = _require_agent(db, agent_id, organization_id)
    agent.status = AgentStatus.DEACTIVATED.value
    # Revoke all credentials immediately.
    for cred in db.scalars(
        select(AgentCredential).where(
            AgentCredential.agent_id == agent_id,
            AgentCredential.revoked_at.is_(None),
        )
    ).all():
        cred.revoked_at = _now()
        cred.is_active = False
    db.commit()
    db.refresh(agent)
    return agent


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def issue_credential(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
    label: str | None = None,
    expires_in_days: int | None = None,
    rotate: bool = False,
) -> tuple[AgentCredential, str]:
    """Issue a new credential. Returns (credential_row, raw_secret).

    The raw secret is returned exactly once and never stored.
    """
    _require_active_agent(db, agent_id, organization_id)

    raw = generate_agent_credential()
    expires_at = _now() + timedelta(days=expires_in_days) if expires_in_days else None

    cred = AgentCredential(
        agent_id=agent_id,
        label=label,
        credential_prefix=credential_display_prefix(raw),
        credential_hash=hash_agent_credential(raw),
        expires_at=expires_at,
        is_active=True,
    )
    if rotate:
        for old_credential in db.scalars(
            select(AgentCredential).where(
                AgentCredential.agent_id == agent_id,
                AgentCredential.revoked_at.is_(None),
                AgentCredential.is_active.is_(True),
            )
        ).all():
            old_credential.revoked_at = _now()
            old_credential.is_active = False
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred, raw


def list_credentials(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
) -> list[AgentCredential]:
    _require_agent(db, agent_id, organization_id)
    return list(
        db.scalars(
            select(AgentCredential)
            .where(AgentCredential.agent_id == agent_id)
            .order_by(AgentCredential.created_at)
        ).all()
    )


def revoke_credential(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
    credential_id: UUID,
) -> AgentCredential:
    _require_agent(db, agent_id, organization_id)
    cred = db.scalar(
        select(AgentCredential).where(
            AgentCredential.id == credential_id,
            AgentCredential.agent_id == agent_id,
        )
    )
    if cred is None:
        raise AppError("Credential not found.", code="not_found", status_code=404)
    if cred.revoked_at is not None:
        raise AppError(
            "Credential is already revoked.",
            code="credential_already_revoked",
            status_code=409,
        )
    cred.revoked_at = _now()
    cred.is_active = False
    db.commit()
    db.refresh(cred)
    return cred


def authenticate_agent(db: Session, *, raw_credential: str) -> Agent:
    """Authenticate a machine-to-machine request by raw API key.

    Raises 401 for unknown, revoked, expired or inactive-agent credentials.
    Updates last_used_at on success.
    """
    credential_hash = hash_agent_credential(raw_credential)
    cred = db.scalar(
        select(AgentCredential).where(AgentCredential.credential_hash == credential_hash)
    )

    if cred is None or cred.revoked_at is not None or not cred.is_active:
        raise AppError(
            "Invalid agent credential.",
            code="invalid_agent_credential",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if cred.expires_at is not None:
        expires = cred.expires_at if cred.expires_at.tzinfo else cred.expires_at.replace(tzinfo=UTC)
        if expires <= _now():
            raise AppError(
                "Agent credential has expired.",
                code="agent_credential_expired",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

    agent = db.get(Agent, cred.agent_id)
    if agent is None or agent.status != AgentStatus.ACTIVE:
        raise AppError(
            "Agent is not active.",
            code="agent_not_active",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    cred.last_used_at = _now()
    db.commit()
    return agent


# ---------------------------------------------------------------------------
# Webhook configuration
# ---------------------------------------------------------------------------


def configure_webhook(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
    webhook_url: str,
    rotate_secret: bool = False,
) -> tuple[Agent, str | None]:
    """Set or update the webhook URL. Generates a new secret if none exists
    or if ``rotate_secret`` is True.

    Returns (agent, plaintext_secret_or_None).
    The plaintext secret is only returned when a new one is generated.
    """
    agent = _require_agent(db, agent_id, organization_id)
    validate_webhook_url(webhook_url)

    agent.webhook_url = webhook_url

    plaintext_secret: str | None = None
    if agent.webhook_secret_encrypted is None or rotate_secret:
        plaintext_secret = generate_webhook_secret()
        agent.webhook_secret_encrypted = encrypt_webhook_secret(plaintext_secret)

    db.commit()
    db.refresh(agent)
    return agent, plaintext_secret


def get_webhook_secret(db: Session, *, agent_id: UUID, organization_id: UUID) -> str | None:
    """Return the decrypted webhook secret for internal use (e.g. delivery).

    Never expose this in API responses.
    """
    agent = _require_agent(db, agent_id, organization_id)
    if agent.webhook_secret_encrypted is None:
        return None
    return decrypt_webhook_secret(agent.webhook_secret_encrypted)
