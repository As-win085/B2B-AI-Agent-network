"""Organization API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.validation import NormalizedEmail

OrganizationRoleName = Literal["owner", "admin", "member"]
AssignableRoleName = Literal["admin", "member"]


class OrganizationResponse(BaseModel):
    """An organization as seen from the caller's membership."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    is_active: bool
    role: OrganizationRoleName


class MemberResponse(BaseModel):
    """A membership row with the member's public identity."""

    id: UUID
    user_id: UUID
    email: str
    full_name: str | None
    role: OrganizationRoleName
    joined_at: datetime


class UpdateOrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Organization name must not be blank.")
        return stripped


class AddMemberRequest(BaseModel):
    email: NormalizedEmail
    role: AssignableRoleName = "member"


class SwitchOrganizationRequest(BaseModel):
    organization_id: UUID


class SwitchOrganizationResponse(BaseModel):
    organization: OrganizationResponse
