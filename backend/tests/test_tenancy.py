"""ASAMA-102: tenant-scoped queries always carry the tenant predicate."""

from __future__ import annotations

from unittest.mock import Mock
from uuid import uuid4

from app.models import OrganizationMember
from app.shared.tenancy import TenantScopedRepository


def _compiled(statement: object) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]


def _repository(organization_id) -> TenantScopedRepository:  # type: ignore[type-arg]
    return TenantScopedRepository(Mock(), OrganizationMember, organization_id)


def test_statement_filters_by_organization() -> None:
    organization_id = uuid4()
    sql = _compiled(_repository(organization_id).statement())

    assert "organization_members.organization_id" in sql
    assert organization_id.hex in sql


def test_get_statement_filters_by_organization_and_id() -> None:
    organization_id = uuid4()
    member_id = uuid4()
    sql = _compiled(_repository(organization_id).get_statement(member_id))

    assert "organization_members.organization_id" in sql
    assert "organization_members.id" in sql
    assert organization_id.hex in sql
    assert member_id.hex in sql


def test_repository_exposes_its_tenant() -> None:
    organization_id = uuid4()
    assert _repository(organization_id).organization_id == organization_id
