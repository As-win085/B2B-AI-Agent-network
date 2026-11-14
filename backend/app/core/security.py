"""Security primitives.

Password hashing, JWT issuance and webhook-signature helpers are implemented in
the phases that introduce authentication (Phase 3) and delivery (Phase 7).
"""

from __future__ import annotations

import hmac


def constant_time_compare(left: str, right: str) -> bool:
    """Compare two strings without leaking timing information."""

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
