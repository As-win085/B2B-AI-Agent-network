"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.core.dependencies import DbSession
from app.core.responses import ApiResponse, success
from app.modules.auth import service
from app.modules.auth.dependencies import PrincipalDep
from app.modules.auth.schemas import (
    AuthSessionResponse,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    UserResponse,
)
from app.modules.organizations.service import organization_payload

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _issued_payload(issued: service.IssuedSession) -> dict:
    return {
        "access_token": issued.access_token,
        "refresh_token": issued.refresh_token,
        "token_type": "bearer",
        "expires_in": issued.expires_in,
        "user": issued.user,
        "organization": (
            organization_payload(issued.active.membership, issued.active.organization)
            if issued.active
            else None
        ),
        "organizations": [
            organization_payload(view.membership, view.organization) for view in issued.memberships
        ],
    }


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[AuthSessionResponse],
    response_model_exclude_none=True,
)
def register(
    payload: RegisterRequest,
    request: Request,
    db: DbSession,
) -> dict:
    """Create a user, an organization and the owner membership atomically."""

    issued = service.register(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
        organization_slug=payload.organization_slug,
        user_agent=_user_agent(request),
        ip_address=_client_ip(request),
    )
    return success(_issued_payload(issued))


@router.post(
    "/login",
    response_model=ApiResponse[AuthSessionResponse],
    response_model_exclude_none=True,
)
def login(
    payload: LoginRequest,
    request: Request,
    db: DbSession,
) -> dict:
    """Exchange credentials for an access token and a refresh session."""

    issued = service.login(
        db,
        email=payload.email,
        password=payload.password,
        user_agent=_user_agent(request),
        ip_address=_client_ip(request),
    )
    return success(_issued_payload(issued))


@router.post(
    "/refresh",
    response_model=ApiResponse[AuthSessionResponse],
    response_model_exclude_none=True,
)
def refresh(
    payload: RefreshRequest,
    request: Request,
    db: DbSession,
) -> dict:
    """Rotate a refresh token and issue a new access token."""

    issued = service.rotate(
        db,
        refresh_token=payload.refresh_token,
        user_agent=_user_agent(request),
        ip_address=_client_ip(request),
    )
    return success(_issued_payload(issued))


@router.post("/logout", response_model=ApiResponse[dict])
def logout(payload: LogoutRequest, db: DbSession) -> dict:
    """Revoke the refresh-token family. Idempotent for unknown tokens."""

    service.logout(db, refresh_token=payload.refresh_token)
    return success({"logged_out": True})


@router.get("/me", response_model=ApiResponse[MeResponse], response_model_exclude_none=True)
def me(principal: PrincipalDep) -> dict:
    """Return the authenticated user and their organization context."""

    active = principal.active
    return success(
        {
            "user": UserResponse.model_validate(principal.user),
            "organization": (
                organization_payload(active.membership, active.organization) if active else None
            ),
            "organizations": [
                organization_payload(view.membership, view.organization)
                for view in principal.memberships
            ],
        }
    )
