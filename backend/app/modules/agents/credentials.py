"""Agent credential security primitives.

Agent API keys are opaque random strings with a fixed prefix ``asa_`` so they
are recognisable in logs and can be caught by secret-scanning tools.

Format:  asa_<48 url-safe base64 chars>
Example: asa_Xk2mN9...

Only the SHA-256 hex digest is stored. The raw key is returned once at
creation and never persisted.
"""

from __future__ import annotations

import hashlib
import secrets

CREDENTIAL_PREFIX = "asa_"
CREDENTIAL_RANDOM_BYTES = 36  # 48 base64 chars after encoding


def generate_agent_credential() -> str:
    """Return a new opaque agent API key. Never stored in plaintext."""
    return CREDENTIAL_PREFIX + secrets.token_urlsafe(CREDENTIAL_RANDOM_BYTES)


def hash_agent_credential(raw: str) -> str:
    """Return the SHA-256 hex digest used to look up a credential."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def credential_display_prefix(raw: str) -> str:
    """Return the first 8 characters of the raw key for display purposes."""
    return raw[:8]
