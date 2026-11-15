"""ASAMA-104 service tests that do not depend on the ASGI test client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.agents.service import (
    authenticate_agent,
    get_agent,
    issue_credential,
    register_agent,
    suspend_agent,
)
from app.modules.organizations.models import Organization


def _organization(db: Session, slug: str = "service-test") -> Organization:
    organization = Organization(name="Service Test", slug=slug)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


def test_credential_rotation_revokes_old_key(db: Session) -> None:
    organization = _organization(db)
    agent = register_agent(
        db,
        organization_id=organization.id,
        company_name="Service Agent",
        industry_category=None,
        interest_manifesto=None,
    )
    old_credential, old_secret = issue_credential(
        db, agent_id=agent.id, organization_id=organization.id
    )
    new_credential, new_secret = issue_credential(
        db, agent_id=agent.id, organization_id=organization.id, rotate=True
    )

    assert old_credential.revoked_at is not None
    assert old_credential.is_active is False
    assert authenticate_agent(db, raw_credential=new_secret).id == agent.id
    with pytest.raises(AppError, match="Invalid agent credential"):
        authenticate_agent(db, raw_credential=old_secret)
    assert new_credential.revoked_at is None


def test_expired_credential_is_rejected(db: Session) -> None:
    organization = _organization(db)
    agent = register_agent(
        db,
        organization_id=organization.id,
        company_name="Service Agent",
        industry_category=None,
        interest_manifesto=None,
    )
    credential, secret = issue_credential(
        db, agent_id=agent.id, organization_id=organization.id, expires_in_days=1
    )
    credential.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    with pytest.raises(AppError, match="expired"):
        authenticate_agent(db, raw_credential=secret)


def test_suspended_agent_credential_is_rejected(db: Session) -> None:
    organization = _organization(db)
    agent = register_agent(
        db,
        organization_id=organization.id,
        company_name="Service Agent",
        industry_category=None,
        interest_manifesto=None,
    )
    _credential, secret = issue_credential(db, agent_id=agent.id, organization_id=organization.id)
    suspend_agent(db, agent_id=agent.id, organization_id=organization.id)

    with pytest.raises(AppError, match="not active"):
        authenticate_agent(db, raw_credential=secret)


def test_agent_lookup_is_tenant_scoped(db: Session) -> None:
    organization = _organization(db, "service-owner")
    other = _organization(db, "service-other")
    agent = register_agent(
        db,
        organization_id=organization.id,
        company_name="Service Agent",
        industry_category=None,
        interest_manifesto=None,
    )

    with pytest.raises(AppError) as error:
        get_agent(db, agent_id=agent.id, organization_id=other.id)
    assert error.value.status_code == 404
