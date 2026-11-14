"""Transactional outbox (Phase 6).

A post and its ``post.published`` outbox row are committed in the same database
transaction. A separate publisher process moves committed outbox rows into
Redis Streams and marks them published.

Implemented in Phase 6; Sprint 1 only establishes the module boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class OutboxEvent:
    id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict
    created_at: datetime = field(default_factory=datetime.utcnow)
