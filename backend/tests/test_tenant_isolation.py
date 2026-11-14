"""ASAMA-102: live tenant-isolation proof against PostgreSQL.

Runs inside a transaction that is always rolled back, so it does not leave data
behind. Skipped unless ``RUN_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.database import engine
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
)
from app.shared.tenancy import TenantScopedRepository

pytestmark = pytest.mark.integration


def test_repository_isolates_organizations() -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection)
        try:
            suffix = uuid.uuid4().hex[:12]
            org_a = Organization(name="Tenant A", slug=f"tenant-a-{suffix}")
            org_b = Organization(name="Tenant B", slug=f"tenant-b-{suffix}")
            user_a = User(email=f"owner-a-{suffix}@example.test")
            user_b = User(email=f"owner-b-{suffix}@example.test")
            session.add_all([org_a, org_b, user_a, user_b])
            session.flush()

            member_a = OrganizationMember(
                organization_id=org_a.id,
                user_id=user_a.id,
                role=OrganizationRole.OWNER.value,
            )
            member_b = OrganizationMember(
                organization_id=org_b.id,
                user_id=user_b.id,
                role=OrganizationRole.MEMBER.value,
            )
            session.add_all([member_a, member_b])
            session.flush()

            repository = TenantScopedRepository(session, OrganizationMember, org_a.id)

            assert [member.id for member in repository.list_all()] == [member_a.id]
            assert repository.get(member_a.id) is not None
            assert repository.get(member_b.id) is None

            # The row exists; it is the tenant predicate that hides it.
            assert session.get(OrganizationMember, member_b.id) is not None
        finally:
            session.close()
            transaction.rollback()
