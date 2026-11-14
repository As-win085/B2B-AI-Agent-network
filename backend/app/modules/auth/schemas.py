"""Authentication API schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import PASSWORD_MAX_LENGTH, password_policy_error
from app.modules.organizations.schemas import OrganizationResponse
from app.shared.validation import NormalizedEmail

_SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$"


class RegisterRequest(BaseModel):
    email: NormalizedEmail
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    full_name: str | None = Field(default=None, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)
    organization_slug: str | None = Field(
        default=None,
        min_length=3,
        max_length=100,
        pattern=_SLUG_PATTERN,
    )

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        error = password_policy_error(value)
        if error:
            raise ValueError(error)
        return value

    @field_validator("full_name")
    @classmethod
    def _blank_full_name_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("organization_name")
    @classmethod
    def _strip_organization_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Organization name must not be blank.")
        return stripped

    @field_validator("organization_slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(_SLUG_PATTERN, value):
            raise ValueError("Use lowercase letters, numbers and single hyphens.")
        return value


class LoginRequest(BaseModel):
    email: NormalizedEmail
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=512)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    created_at: datetime


class AuthSessionResponse(BaseModel):
    """Issued credentials plus the tenant context the client should show."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserResponse
    organization: OrganizationResponse | None = None
    organizations: list[OrganizationResponse] = Field(default_factory=list)


class MeResponse(BaseModel):
    user: UserResponse
    organization: OrganizationResponse | None = None
    organizations: list[OrganizationResponse] = Field(default_factory=list)
