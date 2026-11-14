"""Model registry.

Importing this module registers every ORM model on ``Base.metadata``. Alembic
(``migrations/env.py``) and metadata tests import it so new model modules are
never silently missing from migrations.

Add every new model module to this list in the phase that introduces it.
"""

from __future__ import annotations

from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
)

__all__ = [
    "Organization",
    "OrganizationMember",
    "OrganizationRole",
    "User",
]
