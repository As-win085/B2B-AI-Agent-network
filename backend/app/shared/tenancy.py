"""Tenant-scoped query helpers.

Application code must never build a query against a tenant-owned table without
an ``organization_id`` predicate. :class:`TenantScopedRepository` centralises
that predicate so authorization does not depend on every call site remembering
to add it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session


class TenantScopedRepository[ModelT]:
    """Base repository for models that own an ``organization_id`` column.

    The repository only exposes statements that already include the tenant
    predicate. Callers cannot accidentally issue an unscoped read through it.
    """

    def __init__(self, session: Session, model: type[ModelT], organization_id: UUID) -> None:
        self._session = session
        self._model = model
        self._organization_id = organization_id

    @property
    def organization_id(self) -> UUID:
        return self._organization_id

    def statement(self) -> Select[Any]:
        """Return a SELECT already constrained to this tenant."""

        return select(self._model).where(
            self._model.organization_id == self._organization_id  # type: ignore[attr-defined]
        )

    def get_statement(self, entity_id: UUID) -> Select[Any]:
        """Return a tenant-constrained SELECT for one row."""

        return self.statement().where(
            self._model.id == entity_id  # type: ignore[attr-defined]
        )

    def list_all(self) -> list[ModelT]:
        """Return every row owned by the tenant."""

        return list(self._session.scalars(self.statement()).all())

    def get(self, entity_id: UUID) -> ModelT | None:
        """Return one row when it belongs to the tenant, otherwise ``None``."""

        return self._session.scalars(self.get_statement(entity_id)).one_or_none()
