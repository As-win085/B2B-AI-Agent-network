"""Agent API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RegisterAgentRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    industry_category: str | None = Field(default=None, max_length=100)
    interest_manifesto: str | None = Field(default=None, max_length=10_000)

    @field_validator("company_name")
    @classmethod
    def _strip_company_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Company name must not be blank.")
        return stripped


class UpdateAgentRequest(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    industry_category: str | None = Field(default=None, max_length=100)
    interest_manifesto: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> UpdateAgentRequest:
        if all(
            v is None for v in (self.company_name, self.industry_category, self.interest_manifesto)
        ):
            raise ValueError("Provide at least one field to update.")
        return self

    @field_validator("company_name")
    @classmethod
    def _strip_company_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("Company name must not be blank.")
        return stripped


class UpdateManifestoRequest(BaseModel):
    interest_manifesto: str = Field(min_length=1, max_length=10_000)


class AgentStatusAction(BaseModel):
    action: Literal["suspend", "reactivate", "deactivate"]


class IssueCredentialRequest(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    rotate: bool = False


class WebhookConfigRequest(BaseModel):
    webhook_url: str = Field(min_length=1, max_length=2048)
    rotate_secret: bool = False


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    company_name: str
    industry_category: str | None
    interest_manifesto: str | None
    webhook_url: str | None
    webhook_configured: bool
    status: str
    embedding_generation: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_agent(cls, agent: object) -> AgentResponse:
        from app.modules.agents.models import Agent

        a: Agent = agent  # type: ignore[assignment]
        return cls(
            id=a.id,
            organization_id=a.organization_id,
            company_name=a.company_name,
            industry_category=a.industry_category,
            interest_manifesto=a.interest_manifesto,
            webhook_url=a.webhook_url,
            webhook_configured=a.webhook_secret_encrypted is not None,
            status=a.status,
            embedding_generation=a.embedding_generation,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )


class CredentialResponse(BaseModel):
    """Credential metadata — never includes the raw secret."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    label: str | None
    credential_prefix: str
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class IssuedCredentialResponse(BaseModel):
    """Returned once at creation — includes the raw secret."""

    credential: CredentialResponse
    secret: str  # shown exactly once, never stored


class WebhookConfigResponse(BaseModel):
    webhook_url: str
    webhook_configured: bool
    # signing_secret is only present when a new secret was just generated
    signing_secret: str | None = None
