"""Model registry.

Importing this module registers every ORM model on ``Base.metadata``. Alembic
(``migrations/env.py``) and metadata tests import it so new model modules are
never silently missing from migrations.

Add every new model module to this list in the phase that introduces it.
"""

from __future__ import annotations

from app.events.outbox import OutboxEvent
from app.modules.agents.models import Agent, AgentCredential, AgentStatus
from app.modules.auth.models import RefreshSession, User
from app.modules.comments.models import Comment
from app.modules.organizations.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
)
from app.modules.posts.models import Post, PostStatus
from app.modules.routing.models import (
    AgentBlock,
    AgentEmbeddingVersion,
    RerankStatus,
    RoutingDecision,
    RoutingLog,
)

__all__ = [
    "Agent",
    "AgentBlock",
    "AgentCredential",
    "AgentEmbeddingVersion",
    "AgentStatus",
    "Comment",
    "Organization",
    "OrganizationMember",
    "OrganizationRole",
    "OutboxEvent",
    "Post",
    "PostStatus",
    "RefreshSession",
    "RerankStatus",
    "RoutingDecision",
    "RoutingLog",
    "User",
]
