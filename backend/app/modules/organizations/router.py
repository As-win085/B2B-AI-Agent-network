"""Organization endpoints.

All routes are tenant-scoped: the caller's membership is loaded from
``organization_members`` before anything else, and the path
``organization_id`` is only a selector, never proof of authorization.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.core.dependencies import DbSession
from app.core.responses import ApiResponse, success
from app.modules.auth.dependencies import PrincipalDep
from app.modules.organizations import service
from app.modules.organizations.schemas import (
    AddMemberRequest,
    MemberResponse,
    OrganizationResponse,
    SwitchOrganizationRequest,
    SwitchOrganizationResponse,
    UpdateOrganizationRequest,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])

ADMIN = service.ADMIN


@router.get("", response_model=ApiResponse[list[OrganizationResponse]])
def list_organizations(principal: PrincipalDep) -> dict:
    """List every organization the caller belongs to, with their role."""

    return success(
        [
            service.organization_payload(view.membership, view.organization)
            for view in principal.memberships
        ]
    )


@router.post("/switch", response_model=ApiResponse[SwitchOrganizationResponse])
def switch_organization(
    payload: SwitchOrganizationRequest,
    principal: PrincipalDep,
    db: DbSession,
) -> dict:
    """Make one of the caller's organizations active for this session."""

    view = service.switch_active_organization(
        db,
        user_id=principal.user.id,
        session_id=principal.session.id,
        organization_id=payload.organization_id,
    )
    return success(
        {"organization": service.organization_payload(view.membership, view.organization)}
    )


@router.get("/{organization_id}/members", response_model=ApiResponse[list[MemberResponse]])
def list_members(
    organization_id: UUID,
    principal: PrincipalDep,
    db: DbSession,
) -> dict:
    """List members of an organization the caller belongs to (member and above)."""

    organization, _membership = service.resolve_membership(
        db,
        user_id=principal.user.id,
        organization_id=organization_id,
    )
    rows = service.list_members(db, organization_id=organization.id)
    return success([service.member_payload(member, user) for member, user in rows])


@router.post(
    "/{organization_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[MemberResponse],
)
def add_member(
    organization_id: UUID,
    payload: AddMemberRequest,
    principal: PrincipalDep,
    db: DbSession,
) -> dict:
    """Add an existing user to the organization (admin and above)."""

    organization, membership = service.resolve_membership(
        db,
        user_id=principal.user.id,
        organization_id=organization_id,
    )
    member, user = service.add_member(
        db,
        organization=organization,
        actor_role=membership.role,
        email=payload.email,
        role=payload.role,
    )
    return success(service.member_payload(member, user))


@router.patch("/{organization_id}", response_model=ApiResponse[OrganizationResponse])
def update_organization(
    organization_id: UUID,
    payload: UpdateOrganizationRequest,
    principal: PrincipalDep,
    db: DbSession,
) -> dict:
    """Rename an organization (admin and above)."""

    organization, membership = service.resolve_membership(
        db,
        user_id=principal.user.id,
        organization_id=organization_id,
    )
    service.ensure_at_least(membership.role, ADMIN)

    organization = service.update_organization(db, organization=organization, name=payload.name)
    return success(service.organization_payload(membership, organization))


@router.delete(
    "/{organization_id}/members/{member_id}",
    response_model=ApiResponse[dict],
)
def remove_member(
    organization_id: UUID,
    member_id: UUID,
    principal: PrincipalDep,
    db: DbSession,
) -> dict:
    """Remove a membership. Owners are protected; only owners remove admins."""

    organization, membership = service.resolve_membership(
        db,
        user_id=principal.user.id,
        organization_id=organization_id,
    )
    service.remove_member(
        db,
        organization_id=organization.id,
        actor_role=membership.role,
        membership_id=member_id,
    )
    return success({"removed": True})
