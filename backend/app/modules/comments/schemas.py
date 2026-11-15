"""Comment API request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.comments.models import MAX_COMMENT_LENGTH


class CreateCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)

    @field_validator("content")
    @classmethod
    def trim_and_validate(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Comment content must not be blank.")
        return content


class CommentAuthorResponse(BaseModel):
    id: UUID
    company_name: str


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    post_id: UUID
    author_agent_id: UUID
    content: str
    created_at: datetime
    updated_at: datetime
    author: CommentAuthorResponse


class CommentDeleteResponse(BaseModel):
    id: UUID
    deleted: bool
