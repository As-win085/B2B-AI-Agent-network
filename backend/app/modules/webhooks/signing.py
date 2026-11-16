"""HMAC-SHA256 webhook signatures (FR-20).

The signature is the hex HMAC-SHA256 of ``f"{timestamp}.{body}"`` keyed with
the recipient agent's webhook secret. Signing the timestamp together with the
body binds the signature to one point in time, so a captured request cannot be
replayed later with a fresh timestamp, and any modification of the body or the
timestamp invalidates the signature.

Receivers verify by recomputing:

    expected = hmac_sha256(secret, f"{X-Asama-Timestamp}.{raw_body}")
    hmac.compare_digest(expected, X-Asama-Signature)

Secrets are decrypted only in memory for the duration of one attempt and are
never logged or returned by any API.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "X-Asama-Signature"
EVENT_ID_HEADER = "X-Asama-Event-Id"
EVENT_TYPE_HEADER = "X-Asama-Event-Type"
TIMESTAMP_HEADER = "X-Asama-Timestamp"


def compute_signature(secret: str, *, timestamp: str, body: bytes) -> str:
    """Hex HMAC-SHA256 over ``timestamp.body`` (FR-20)."""
    message = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_signature(secret: str, *, timestamp: str, body: bytes, signature: str) -> bool:
    """Constant-time verification helper for receivers and tests."""
    expected = compute_signature(secret, timestamp=timestamp, body=body)
    return hmac.compare_digest(expected, signature)


def delivery_headers(
    *, event_id: str, event_type: str, timestamp: str, signature: str
) -> dict[str, str]:
    """The four plan-mandated delivery headers."""
    return {
        EVENT_ID_HEADER: event_id,
        EVENT_TYPE_HEADER: event_type,
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: signature,
    }
