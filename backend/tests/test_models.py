"""ASAMA-102: model registry and constraint conventions."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import app.models  # noqa: F401 - registers models on Base.metadata
from app.core.database import Base


def test_tenancy_tables_are_registered() -> None:
    assert {"organizations", "users", "organization_members"} <= set(Base.metadata.tables)


def test_primary_key_names_follow_convention() -> None:
    for table_name in ("organizations", "users", "organization_members"):
        table = Base.metadata.tables[table_name]
        assert table.primary_key.name == f"pk_{table_name}"


def test_organizations_have_unique_slug() -> None:
    table = Base.metadata.tables["organizations"]
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_organizations_slug" in unique_names


def test_users_have_unique_email() -> None:
    table = Base.metadata.tables["users"]
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_users_email" in unique_names


def test_membership_has_composite_unique_and_role_check() -> None:
    table = Base.metadata.tables["organization_members"]

    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_organization_members_organization_id_user_id" in unique_names

    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_organization_members_role_valid" in check_names


def test_membership_foreign_keys_cascade() -> None:
    table = Base.metadata.tables["organization_members"]
    foreign_keys = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert (
        foreign_keys["fk_organization_members_organization_id_organizations"].ondelete == "CASCADE"
    )
    assert foreign_keys["fk_organization_members_user_id_users"].ondelete == "CASCADE"

    for constraint in foreign_keys.values():
        assert constraint.elements
        assert all(
            element.column.table.name in {"organizations", "users"}
            for element in constraint.elements
        )


def test_tenant_columns_are_indexed() -> None:
    table = Base.metadata.tables["organization_members"]
    index_names = {index.name for index in table.indexes}
    assert "ix_organization_members_organization_id" in index_names
    assert "ix_organization_members_user_id" in index_names


def test_users_are_not_tenant_owned() -> None:
    assert "organization_id" not in Base.metadata.tables["users"].columns
    assert "organization_id" in Base.metadata.tables["organization_members"].columns
