"""Organization, membership and role models.

Tenancy is enforced through ``organization_members``: every user reaches tenant
data through a membership row, and every tenant-owned table carries an
``organization_id`` foreign key.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.models import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.auth.models import User


class OrganizationRole(StrEnum):
    """Roles a human can hold inside one organization."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


_ROLE_VALUES = ", ".join(f"'{role.value}'" for role in OrganizationRole)


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A tenant (company workspace)."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )

    members: Mapped[list[OrganizationMember]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class OrganizationMember(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """Membership of one user in one organization, with a role."""

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_members_organization_id_user_id",
        ),
        CheckConstraint(f"role IN ({_ROLE_VALUES})", name="role_valid"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'member'"),
    )

    organization: Mapped[Organization] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")
