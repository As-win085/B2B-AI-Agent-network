"""Organization role ordering.

Roles are hierarchical for management operations: an owner can manage admins,
an admin can manage members, and a member can only read.
"""

from __future__ import annotations

ROLE_RANK: dict[str, int] = {
    "member": 1,
    "admin": 2,
    "owner": 3,
}


def role_at_least(role: str, minimum: str) -> bool:
    """Return whether ``role`` is at least as privileged as ``minimum``."""

    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(minimum, 0)
