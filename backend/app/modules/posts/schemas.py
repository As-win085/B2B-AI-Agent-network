"""Post request and response schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PostStatusValue = Literal["processing", "published", "failed", "archived", "expired"]


def _validate_expiry(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Expiry must include a timezone.")
    if value <= datetime.now(UTC):
        raise ValueError("Expiry must be in the future.")
    return value


class CreatePostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=20_000)
    expires_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("Title must not be blank.")
        return result

    @field_validator("content")
    @classmethod
    def _clean_content(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("Content must not be blank.")
        return result

    @field_validator("expires_at")
    @classmethod
    def _valid_expiry(cls, value: datetime | None) -> datetime | None:
        return _validate_expiry(value)


class UpdatePostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=20_000)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _has_field(self) -> UpdatePostRequest:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        return self

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Title cannot be null.")
        result = value.strip()
        if not result:
            raise ValueError("Title must not be blank.")
        return result

    @field_validator("content")
    @classmethod
    def _clean_content(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Content cannot be null.")
        result = value.strip()
        if not result:
            raise ValueError("Content must not be blank.")
        return result

    @field_validator("expires_at")
    @classmethod
    def _valid_expiry(cls, value: datetime | None) -> datetime | None:
        return _validate_expiry(value)


class PostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    author_agent_id: UUID
    title: str
    content: str
    status: PostStatusValue
    expires_at: datetime | None
    published_at: datetime | None
    archived_at: datetime | None
    embedding_provider: str | None
    embedding_model: str | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_post(cls, post) -> PostResponse:
        response = cls.model_validate(post)
        if (
            response.status == "published"
            and response.expires_at is not None
            and response.expires_at <= datetime.now(UTC)
        ):
            response.status = "expired"
        return response
