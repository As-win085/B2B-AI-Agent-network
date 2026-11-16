"""Notification API schemas (Phase 7).

The URL and payload are deliberately absent: URLs are recipient webhook
configuration (never exposed, NFR-10) and the signed payload travels only
inside the webhook itself.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationResponse(BaseModel):
    """One delivery record with its FR-16 engagement outcome."""

    id: UUID
    event_id: UUID
    event_type: str
    status: str
    outcome: str
    attempts: int
    max_attempts: int = Field(description="Configured retry bound for this deployment")
    post_id: UUID
    recipient_agent_id: UUID
    response_status: int | None = None
    last_error: str | None = None
    next_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class NotificationSummaryResponse(BaseModel):
    """Delivery-status totals plus FR-16 outcome totals for the tenant."""

    by_status: dict[str, int]
    by_outcome: dict[str, int]
