"""Notification delivery status and retry API (Phase 7).

Visibility rule (tenant-safe, both predicates are caller-tenant checks):

* deliveries of posts published by the caller's organization (sent side —
  FR-15 delivery status for routing audits), and
* deliveries whose recipient agent belongs to the caller's organization
  (received side — the recipient's dashboard).

Cross-tenant and unknown ids both return 404. The webhook URL and signed
payload are never exposed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.core.config import settings
from app.core.dependencies import DbSession
from app.core.responses import ApiResponse, success
from app.modules.auth.dependencies import OrganizationContextDep, require_roles
from app.modules.notifications.schemas import (
    NotificationResponse,
    NotificationSummaryResponse,
)
from app.modules.webhooks import service
from app.modules.webhooks.models import DeliveryStatus, WebhookDelivery

router = APIRouter(prefix="/notifications", tags=["notifications"])
_ADMIN_DEP = require_roles("owner", "admin")


def _to_response(delivery: WebhookDelivery, outcome: str) -> NotificationResponse:
    return NotificationResponse(
        id=delivery.id,
        event_id=delivery.event_id,
        event_type=delivery.event_type,
        status=delivery.status,
        outcome=outcome,
        attempts=delivery.attempts,
        max_attempts=settings.webhook_max_attempts,
        post_id=delivery.post_id,
        recipient_agent_id=delivery.recipient_agent_id,
        response_status=delivery.response_status,
        last_error=delivery.last_error,
        next_attempt_at=delivery.next_attempt_at,
        last_attempt_at=delivery.last_attempt_at,
        delivered_at=delivery.delivered_at,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
    )


@router.get("/summary", response_model=ApiResponse[NotificationSummaryResponse])
def notification_summary(ctx: OrganizationContextDep, db: DbSession) -> dict:
    """Delivery-status and engagement totals for the caller's organization."""
    summary = service.delivery_summary(db, organization_id=ctx.organization.id)
    return success(NotificationSummaryResponse(**summary))


@router.get("", response_model=ApiResponse[list[NotificationResponse]])
def list_notifications(
    ctx: OrganizationContextDep,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: DeliveryStatus | None = None,
    post_id: UUID | None = None,
) -> dict:
    """Paginated delivery history: sent by or received into this organization."""
    deliveries, total = service.list_deliveries(
        db,
        organization_id=ctx.organization.id,
        status=status.value if status else None,
        post_id=post_id,
        page=page,
        page_size=page_size,
    )
    outcomes = service.engagement_outcomes(db, deliveries)
    return success(
        [_to_response(delivery, outcomes[delivery.id]) for delivery in deliveries],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/{notification_id}",
    response_model=ApiResponse[NotificationResponse],
)
def get_notification(
    notification_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """One delivery record, including attempt counters and last error."""
    delivery = service.get_visible_delivery(
        db, delivery_id=notification_id, organization_id=ctx.organization.id
    )
    outcomes = service.engagement_outcomes(db, [delivery])
    return success(_to_response(delivery, outcomes[delivery.id]))


@router.post(
    "/{notification_id}/retry",
    response_model=ApiResponse[NotificationResponse],
)
def retry_notification(
    notification_id: UUID,
    ctx: OrganizationContextDep,
    db: DbSession,
) -> dict:
    """Re-open a failed or dead delivery with a fresh bounded retry cycle."""
    _ADMIN_DEP(ctx)
    delivery = service.retry_delivery(
        db,
        delivery_id=notification_id,
        organization_id=ctx.organization.id,
    )
    outcomes = service.engagement_outcomes(db, [delivery])
    return success(_to_response(delivery, outcomes[delivery.id]))
