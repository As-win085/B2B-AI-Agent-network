"""Human user accounts.

Authentication (password hashing, JWT issuance) is implemented in the next
task. This model defines the tenant-independent identity record only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.organizations.models import OrganizationMember


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A human account that may belong to one or more organizations."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    memberships: Mapped[list[OrganizationMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
