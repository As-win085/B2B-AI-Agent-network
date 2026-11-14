"""Authentication and tenant-scoped authorization dependencies.

The active organization is resolved **server-side**:

1. The access token is verified and its session is loaded.
2. The session's ``active_organization_id`` selects a membership.
3. That membership is re-read from ``organization_members`` on every request,
   so role changes and removals apply immediately.

A caller can switch the active organization only through
``POST /api/v1/organizations/switch``, which validates membership first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import DbSession
from app.core.exceptions import AppError
from app.core.tokens import TokenValidationError, decode_access_token
from app.modules.auth.models import RefreshSession, User
from app.modules.auth.service import (
    AUTH_HEADERS,
    MembershipView,
    ensure_utc,
    list_memberships,
    pick_active,
)
from app.modules.organizations.models import Organization, OrganizationMember

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="Short-lived JWT access token returned by /api/v1/auth/login.",
)


@dataclass(slots=True)
class Principal:
    """An authenticated user and the session their access token belongs to."""

    user: User
    session: RefreshSession
    memberships: list[MembershipView]

    @property
    def active(self) -> MembershipView | None:
        return pick_active(self.memberships, self.session.active_organization_id)


@dataclass(slots=True)
class OrganizationContext:
    """A principal plus the resolved membership for the active organization."""

    user: User
    session: RefreshSession
    organization: Organization
    membership: OrganizationMember
    role: str


def unauthorized(code: str, message: str) -> AppError:
    return AppError(message, code=code, status_code=401, headers=AUTH_HEADERS)


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> Principal:
    """Validate the bearer token and load the backing session."""

    if credentials is None:
        raise unauthorized("unauthenticated", "Authentication required.")

    try:
        claims = decode_access_token(credentials.credentials)
    except TokenValidationError as exc:
        raise unauthorized(exc.code, exc.message) from exc

    session = db.get(RefreshSession, claims.session_id)
    if session is None or session.user_id != claims.user_id:
        raise unauthorized("invalid_token", "Access token is invalid.")
    if session.revoked_at is not None:
        raise unauthorized("session_revoked", "Session has been revoked. Sign in again.")
    if ensure_utc(session.expires_at) <= datetime.now(UTC):
        raise unauthorized("session_expired", "Session has expired. Sign in again.")

    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise unauthorized("invalid_token", "Access token is invalid.")

    return Principal(
        user=user,
        session=session,
        memberships=list_memberships(db, user.id),
    )


def get_organization_context(
    principal: Annotated[Principal, Depends(get_principal)],
) -> OrganizationContext:
    """Resolve the active organization from the authenticated membership."""

    active = principal.active
    if active is None:
        raise AppError(
            "Select an organization to continue.",
            code="organization_required",
            status_code=403,
        )

    return OrganizationContext(
        user=principal.user,
        session=principal.session,
        organization=active.organization,
        membership=active.membership,
        role=active.role,
    )


def require_roles(*roles: str) -> Callable[..., OrganizationContext]:
    """Return a dependency that allows only the listed roles."""

    allowed = frozenset(roles)

    def dependency(
        context: Annotated[OrganizationContext, Depends(get_organization_context)],
    ) -> OrganizationContext:
        if context.role not in allowed:
            raise AppError(
                "You do not have permission to perform this action.",
                code="forbidden",
                status_code=403,
            )
        return context

    return dependency


PrincipalDep = Annotated[Principal, Depends(get_principal)]
OrganizationContextDep = Annotated[OrganizationContext, Depends(get_organization_context)]
