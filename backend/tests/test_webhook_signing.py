"""FR-20: HMAC-SHA256 signatures and the mandated delivery headers."""

from __future__ import annotations

import hashlib
import hmac

from app.modules.webhooks.signing import (
    EVENT_ID_HEADER,
    EVENT_TYPE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    compute_signature,
    delivery_headers,
    verify_signature,
)

SECRET = "5e8d3f0a1b2c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6"
BODY = b'{"data":{"post":{"id":"abc"}},"event_type":"post.published"}'
TIMESTAMP = "1795000000"


def test_signature_matches_independent_hmac_sha256() -> None:
    expected = hmac.new(
        SECRET.encode(),
        TIMESTAMP.encode() + b"." + BODY,
        hashlib.sha256,
    ).hexdigest()
    assert compute_signature(SECRET, timestamp=TIMESTAMP, body=BODY) == expected
    assert len(compute_signature(SECRET, timestamp=TIMESTAMP, body=BODY)) == 64


def test_signature_binds_both_timestamp_and_body() -> None:
    original = compute_signature(SECRET, timestamp=TIMESTAMP, body=BODY)

    # A fresh timestamp cannot reuse an old signature (replay defence).
    re_timestamped = compute_signature(SECRET, timestamp="1795000001", body=BODY)
    assert re_timestamped != original

    # Any body modification invalidates the signature.
    tampered = compute_signature(SECRET, timestamp=TIMESTAMP, body=BODY + b" ")
    assert tampered != original

    assert verify_signature(
        SECRET, timestamp=TIMESTAMP, body=BODY, signature=original
    )
    assert not verify_signature(
        SECRET, timestamp="1795000001", body=BODY, signature=original
    )
    assert not verify_signature(
        "another-secret", timestamp=TIMESTAMP, body=BODY, signature=original
    )


def test_delivery_headers_carry_the_four_plan_headers() -> None:
    headers = delivery_headers(
        event_id="evt-1",
        event_type="post.published",
        timestamp=TIMESTAMP,
        signature="abc123",
    )
    assert set(headers) == {
        EVENT_ID_HEADER,
        EVENT_TYPE_HEADER,
        TIMESTAMP_HEADER,
        SIGNATURE_HEADER,
    }
    assert headers[EVENT_ID_HEADER] == "evt-1"
    assert headers[EVENT_TYPE_HEADER] == "post.published"
    assert headers[TIMESTAMP_HEADER] == TIMESTAMP
    assert headers[SIGNATURE_HEADER] == "abc123"
    assert EVENT_ID_HEADER == "X-Asama-Event-Id"
    assert EVENT_TYPE_HEADER == "X-Asama-Event-Type"
    assert TIMESTAMP_HEADER == "X-Asama-Timestamp"
    assert SIGNATURE_HEADER == "X-Asama-Signature"
