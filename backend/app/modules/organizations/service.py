"""Organization membership, switching and administration.

Authorization for path-selected organizations is always derived from a
membership row. A caller acting on an organization they do not belong to
receives 404, so the API never confirms that another tenant exists.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.auth.models import RefreshSession, User
from app.modules.auth.service import MembershipView
from app.modules.organizations.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
)
from app.modules.organizations.roles import role_at_least

ADMIN = OrganizationRole.ADMIN.value
OWNER = OrganizationRole.OWNER.value
MEMBER = OrganizationRole.MEMBER.value


def organization_payload(membership: OrganizationMember, organization: Organization) -> dict:
    """Serialise an organization together with the caller's role in it."""

    return {
        "id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
        "is_active": organization.is_active,
        "role": membership.role,
    }


def member_payload(membership: OrganizationMember, user: User) -> dict:
    """Serialise a membership with the member's public identity."""

    return {
        "id": membership.id,
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": membership.role,
        "joined_at": membership.created_at,
    }


def resolve_membership(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> tuple[Organization, OrganizationMember]:
    """Return the caller's membership for a path-selected organization."""

    row = db.execute(
        select(OrganizationMember, Organization)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == organization_id,
        )
    ).first()

    if row is None:
        raise AppError("Organization not found.", code="not_found", status_code=404)

    membership, organization = row
    return organization, membership


def ensure_at_least(role: str, minimum: str) -> None:
    """Raise 403 unless ``role`` meets the minimum required role."""

    if not role_at_least(role, minimum):
        raise AppError(
            "You do not have permission to perform this action.",
            code="forbidden",
            status_code=403,
        )


def switch_active_organization(
    db: Session,
    *,
    user_id: UUID,
    session_id: UUID,
    organization_id: UUID,
) -> MembershipView:
    """Validate membership and make the organization active for this session."""

    organization, membership = resolve_membership(
        db,
        user_id=user_id,
        organization_id=organization_id,
    )
    if not organization.is_active:
        raise AppError(
            "This organization is inactive.",
            code="organization_inactive",
            status_code=403,
        )

    session = db.get(RefreshSession, session_id)
    if session is None or session.user_id != user_id:
        raise AppError("Session not found.", code="invalid_token", status_code=401)

    session.active_organization_id = organization.id
    db.commit()

    return MembershipView(membership=membership, organization=organization)


def list_members(db: Session, *, organization_id: UUID) -> list[tuple[OrganizationMember, User]]:
    """Return every member of an organization with their public identity."""

    rows = db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.created_at)
    ).all()
    return [(member, user) for member, user in rows]


def update_organization(
    db: Session,
    *,
    organization: Organization,
    name: str,
) -> Organization:
    """Rename an organization."""

    organization.name = name
    db.commit()
    return organization


def add_member(
    db: Session,
    *,
    organization: Organization,
    actor_role: str,
    email: str,
    role: str,
) -> tuple[OrganizationMember, User]:
    """Add an existing user to the organization with an assignable role."""

    ensure_at_least(actor_role, ADMIN)

    if role not in {ADMIN, MEMBER}:
        raise AppError(
            "Only the owner role cannot be assigned through this endpoint.",
            code="invalid_role",
            status_code=422,
            details=[{"field": "role"}],
        )

    if role_at_least(role, ADMIN) and not role_at_least(actor_role, OWNER):
        raise AppError(
            "Only an owner can grant the admin role.",
            code="forbidden",
            status_code=403,
        )

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise AppError("No user with that email exists.", code="user_not_found", status_code=404)

    existing = db.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == user.id,
        )
    )
    if existing is not None:
        raise AppError(
            "That user is already a member.",
            code="already_member",
            status_code=409,
        )

    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=role,
    )
    db.add(membership)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "That user is already a member.",
            code="already_member",
            status_code=409,
        ) from exc

    return membership, user


def remove_member(
    db: Session,
    *,
    organization_id: UUID,
    actor_role: str,
    membership_id: UUID,
) -> None:
    """Remove a membership, protecting owners and owner-granted admins."""

    ensure_at_least(actor_role, ADMIN)

    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.id == membership_id,
            OrganizationMember.organization_id == organization_id,
        )
    )
    if membership is None:
        raise AppError("Member not found.", code="not_found", status_code=404)

    if membership.role == OWNER:
        raise AppError(
            "The organization owner cannot be removed.",
            code="owner_protected",
            status_code=403,
        )

    if membership.role == ADMIN and not role_at_least(actor_role, OWNER):
        raise AppError(
            "Only an owner can remove an admin.",
            code="forbidden",
            status_code=403,
        )

    db.delete(membership)
    db.commit()
