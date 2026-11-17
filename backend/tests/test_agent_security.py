"""ASAMA-104: agent credential primitives and webhook SSRF protection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.exceptions import AppError
from app.modules.agents.credentials import (
    CREDENTIAL_PREFIX,
    credential_display_prefix,
    generate_agent_credential,
    hash_agent_credential,
)
from app.modules.agents.webhook import (
    decrypt_webhook_secret,
    encrypt_webhook_secret,
    generate_webhook_secret,
    validate_webhook_url,
)

# ---------------------------------------------------------------------------
# Credential primitives
# ---------------------------------------------------------------------------


def test_credential_has_correct_prefix() -> None:
    raw = generate_agent_credential()
    assert raw.startswith(CREDENTIAL_PREFIX)


def test_credentials_are_unique() -> None:
    assert generate_agent_credential() != generate_agent_credential()


def test_credential_hash_is_64_hex_chars() -> None:
    raw = generate_agent_credential()
    digest = hash_agent_credential(raw)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_credential_hash_is_deterministic() -> None:
    raw = generate_agent_credential()
    assert hash_agent_credential(raw) == hash_agent_credential(raw)


def test_credential_hash_differs_for_different_keys() -> None:
    a = generate_agent_credential()
    b = generate_agent_credential()
    assert hash_agent_credential(a) != hash_agent_credential(b)


def test_credential_hash_never_contains_plaintext() -> None:
    raw = generate_agent_credential()
    assert raw not in hash_agent_credential(raw)


def test_display_prefix_is_first_8_chars() -> None:
    raw = generate_agent_credential()
    assert credential_display_prefix(raw) == raw[:8]


# ---------------------------------------------------------------------------
# Webhook secret encryption
# ---------------------------------------------------------------------------


def test_webhook_secret_round_trip() -> None:
    secret = generate_webhook_secret()
    token = encrypt_webhook_secret(secret)
    assert decrypt_webhook_secret(token) == secret


def test_webhook_secrets_are_unique() -> None:
    assert generate_webhook_secret() != generate_webhook_secret()


def test_webhook_secret_is_not_stored_in_plaintext() -> None:
    secret = generate_webhook_secret()
    token = encrypt_webhook_secret(secret)
    assert secret not in token


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",
        "http://127.0.0.1/hook",
        "http://localhost/hook",
        "http://0.0.0.0/hook",
        "http://10.0.0.1/hook",
        "http://172.16.0.1/hook",
        "http://192.168.1.1/hook",
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata
        "http://[::1]/hook",
        "ftp://example.com/hook",
        "file:///etc/passwd",
        "http:///no-host",
    ],
)
def test_ssrf_blocked_urls(url: str) -> None:
    with pytest.raises(AppError) as exc_info:
        validate_webhook_url(url)
    assert exc_info.value.status_code == 422


def test_ssrf_unresolvable_hostname_is_blocked() -> None:
    with pytest.raises(AppError) as exc_info:
        validate_webhook_url("https://this-hostname-does-not-exist.invalid/hook")
    assert exc_info.value.status_code == 422


def test_ssrf_url_too_long_is_blocked() -> None:
    url = "https://example.com/" + "a" * 2048
    with pytest.raises(AppError) as exc_info:
        validate_webhook_url(url)
    assert exc_info.value.status_code == 422


def test_valid_public_url_passes() -> None:
    with patch("app.modules.agents.webhook.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 443))]
        result = validate_webhook_url("https://example.com/webhook")
    assert result == "https://example.com/webhook"


def test_redirect_target_is_revalidated() -> None:
    from app.modules.agents.webhook import validate_webhook_redirect

    with pytest.raises(AppError):
        validate_webhook_redirect("https://example.com/hook", "http://169.254.169.254/latest")


def test_dns_resolution_must_be_rechecked_before_delivery() -> None:
    # First check resolves publicly; a subsequent delivery-time check catches
    # a changed answer, demonstrating the required rebinding defense hook.
    from app.modules.agents.webhook import validate_webhook_url

    with patch("app.modules.agents.webhook.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 443))]
        validate_webhook_url("https://example.com/hook")
        mock_dns.return_value = [(None, None, None, None, ("10.0.0.2", 443))]
        with pytest.raises(AppError):
            validate_webhook_url("https://example.com/hook")
