"""Authentication service: registration, login and refresh-token lifecycle.

Security properties enforced here:

* Emails are normalised before lookup, so ``User@Example.com`` and
  ``user@example.com`` are the same account.
* Login failures are indistinguishable: unknown email, missing password and a
  wrong password all return the same 401 body after a real password hash has
  been evaluated (timing equalisation).
* Refresh tokens are opaque, stored only as SHA-256 hashes, rotated on every
  use and grouped into families. Replaying a rotated token revokes the family.
* Access tokens are bound to a session row, so revocation is immediate.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import (
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    verify_password,
)
from app.core.tokens import create_access_token
from app.modules.auth.models import RefreshSession, User
from app.modules.organizations.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
)
from app.modules.organizations.slugs import unique_slug

AUTH_HEADERS = {"WWW-Authenticate": "Bearer"}

_MEMBERSHIP_ORDER = case(
    (OrganizationMember.role == OrganizationRole.OWNER.value, 0),
    (OrganizationMember.role == OrganizationRole.ADMIN.value, 1),
    else_=2,
)


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime (SQLite returns naive values)."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class MembershipView:
    """A membership joined with its organization."""

    membership: OrganizationMember
    organization: Organization

    @property
    def role(self) -> str:
        return self.membership.role


@dataclass(slots=True)
class IssuedSession:
    """Result of a successful register/login/refresh."""

    user: User
    session_id: UUID
    access_token: str
    expires_in: int
    refresh_token: str
    memberships: list[MembershipView]
    active: MembershipView | None


def list_memberships(db: Session, user_id: UUID) -> list[MembershipView]:
    """Return every membership for a user, owner first, then oldest."""

    rows = db.execute(
        select(OrganizationMember, Organization)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(_MEMBERSHIP_ORDER, OrganizationMember.created_at)
    ).all()
    return [MembershipView(membership=member, organization=org) for member, org in rows]


def pick_active(
    memberships: list[MembershipView],
    preferred_organization_id: UUID | None,
) -> MembershipView | None:
    """Choose the session's active organization, skipping inactive tenants."""

    for view in memberships:
        if not view.organization.is_active:
            continue
        if preferred_organization_id is not None and (
            view.organization.id == preferred_organization_id
        ):
            return view
    for view in memberships:
        if view.organization.is_active:
            return view
    return None


def _trim(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    return value.strip()[:limit]


def _create_session(
    db: Session,
    *,
    user_id: UUID,
    active_organization_id: UUID | None,
    user_agent: str | None,
    ip_address: str | None,
    family_id: UUID | None = None,
) -> tuple[RefreshSession, str]:
    raw_token = generate_refresh_token()
    session = RefreshSession(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        family_id=family_id or uuid4(),
        active_organization_id=active_organization_id,
        user_agent=_trim(user_agent, 255),
        ip_address=_trim(ip_address, 64),
        expires_at=_now() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session)
    db.flush()
    return session, raw_token


def _issue(
    db: Session,
    *,
    user: User,
    memberships: list[MembershipView],
    active: MembershipView | None,
    user_agent: str | None,
    ip_address: str | None,
    family_id: UUID | None = None,
) -> IssuedSession:
    session, refresh_token = _create_session(
        db,
        user_id=user.id,
        active_organization_id=active.organization.id if active else None,
        user_agent=user_agent,
        ip_address=ip_address,
        family_id=family_id,
    )
    access_token, _expires_at = create_access_token(user_id=user.id, session_id=session.id)
    return IssuedSession(
        user=user,
        session_id=session.id,
        access_token=access_token,
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_token=refresh_token,
        memberships=memberships,
        active=active,
    )


def _invalid_credentials() -> AppError:
    return AppError(
        "Invalid email or password.",
        code="invalid_credentials",
        status_code=401,
        headers=AUTH_HEADERS,
    )


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A real hash used to equalise timing when the email does not exist."""

    return hash_password(secrets.token_urlsafe(32))


def register(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str | None,
    organization_name: str,
    organization_slug: str | None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedSession:
    """Create user + organization + owner membership in one transaction."""

    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise AppError(
            "An account with this email already exists.",
            code="email_already_registered",
            status_code=409,
            details=[{"field": "email"}],
        )

    if organization_slug is None:
        slug = unique_slug(db, organization_name)
    else:
        existing = db.scalar(select(Organization.id).where(Organization.slug == organization_slug))
        if existing is not None:
            raise AppError(
                "That organization slug is already taken.",
                code="organization_slug_taken",
                status_code=409,
                details=[{"field": "organization_slug"}],
            )
        slug = organization_slug

    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
    )
    organization = Organization(name=organization_name, slug=slug)

    try:
        db.add_all([user, organization])
        db.flush()
        membership = OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.OWNER.value,
        )
        db.add(membership)
        db.flush()

        memberships = [MembershipView(membership=membership, organization=organization)]
        issued = _issue(
            db,
            user=user,
            memberships=memberships,
            active=memberships[0],
            user_agent=user_agent,
            ip_address=ip_address,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _integrity_error(exc) from exc

    return issued


def login(
    db: Session,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedSession:
    """Verify credentials and open a new refresh-token session."""

    user = db.scalar(select(User).where(User.email == email))

    if user is None or not user.password_hash:
        verify_password(password, _dummy_hash())
        raise _invalid_credentials()

    if not verify_password(password, user.password_hash):
        raise _invalid_credentials()

    if not user.is_active:
        raise AppError(
            "This account is disabled.",
            code="account_disabled",
            status_code=403,
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    memberships = list_memberships(db, user.id)
    active = pick_active(memberships, None)
    issued = _issue(
        db,
        user=user,
        memberships=memberships,
        active=active,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.commit()
    return issued


def rotate(
    db: Session,
    *,
    refresh_token: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedSession:
    """Consume a refresh token, issue a new pair and revoke the old session."""

    token_hash = hash_refresh_token(refresh_token)
    session = db.execute(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash).with_for_update()
    ).scalar_one_or_none()

    if session is None:
        raise _invalid_refresh_token()

    if session.revoked_at is not None:
        # A rotated token was replayed: assume theft and kill the whole family.
        _revoke_family(db, session.family_id, reason="reuse_detected")
        db.commit()
        raise AppError(
            "Refresh token has already been used. Sign in again.",
            code="refresh_token_reused",
            status_code=401,
            headers=AUTH_HEADERS,
        )

    if ensure_utc(session.expires_at) <= _now():
        _revoke_family(db, session.family_id, reason="expired")
        db.commit()
        raise AppError(
            "Refresh token has expired. Sign in again.",
            code="refresh_token_expired",
            status_code=401,
            headers=AUTH_HEADERS,
        )

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        _revoke_family(db, session.family_id, reason="account_inactive")
        db.commit()
        raise _invalid_refresh_token()

    memberships = list_memberships(db, user.id)
    active = pick_active(memberships, session.active_organization_id)

    issued = _issue(
        db,
        user=user,
        memberships=memberships,
        active=active,
        user_agent=user_agent or session.user_agent,
        ip_address=ip_address or session.ip_address,
        family_id=session.family_id,
    )
    session.revoked_at = _now()
    session.revoked_reason = "rotated"
    session.replaced_by_id = issued.session_id
    db.commit()
    return issued


def logout(db: Session, *, refresh_token: str) -> None:
    """Revoke the refresh-token family. Unknown tokens are a no-op."""

    session = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(refresh_token))
    )
    if session is None:
        return
    _revoke_family(db, session.family_id, reason="logout")
    db.commit()


def _revoke_family(db: Session, family_id: UUID, *, reason: str) -> None:
    db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now(), revoked_reason=reason)
    )


def _invalid_refresh_token() -> AppError:
    return AppError(
        "Refresh token is invalid. Sign in again.",
        code="invalid_refresh_token",
        status_code=401,
        headers=AUTH_HEADERS,
    )


def _integrity_error(exc: IntegrityError) -> AppError:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_users_email" in message or "users_email_key" in message:
        return AppError(
            "An account with this email already exists.",
            code="email_already_registered",
            status_code=409,
            details=[{"field": "email"}],
        )
    if "uq_organizations_slug" in message or "organizations_slug_key" in message:
        return AppError(
            "That organization slug is already taken.",
            code="organization_slug_taken",
            status_code=409,
            details=[{"field": "organization_slug"}],
        )
    return AppError(
        "Could not complete registration.",
        code="registration_failed",
        status_code=409,
    )
