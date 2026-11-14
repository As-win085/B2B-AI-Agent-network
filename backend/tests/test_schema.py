"""ASAMA-102: live schema names match the model metadata.

Alembic does not compare CHECK constraints during autogenerate, so their names
are asserted directly against PostgreSQL. Skipped unless
``RUN_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.core.database import engine

pytestmark = pytest.mark.integration


def test_tenancy_tables_exist() -> None:
    inspector = inspect(engine)
    assert {"organizations", "users", "organization_members"} <= set(inspector.get_table_names())


def test_check_constraint_names() -> None:
    inspector = inspect(engine)
    names = {
        constraint["name"] for constraint in inspector.get_check_constraints("organization_members")
    }
    assert names == {"ck_organization_members_role_valid"}


def test_foreign_key_names_and_cascade() -> None:
    inspector = inspect(engine)
    foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("organization_members")
    }

    assert set(foreign_keys) == {
        "fk_organization_members_organization_id_organizations",
        "fk_organization_members_user_id_users",
    }
    for foreign_key in foreign_keys.values():
        assert foreign_key["options"].get("ondelete") == "CASCADE"


def test_unique_constraint_names() -> None:
    inspector = inspect(engine)

    organization_uniques = {
        constraint["name"] for constraint in inspector.get_unique_constraints("organizations")
    }
    user_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("users")}
    member_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("organization_members")
    }

    assert "uq_organizations_slug" in organization_uniques
    assert "uq_users_email" in user_uniques
    assert "uq_organization_members_organization_id_user_id" in member_uniques


def test_tenant_index_names() -> None:
    inspector = inspect(engine)
    names = {index["name"] for index in inspector.get_indexes("organization_members")}
    assert {"ix_organization_members_organization_id", "ix_organization_members_user_id"} <= names
