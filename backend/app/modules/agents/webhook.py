"""Webhook URL validation (SSRF protection) and secret encryption.

SSRF protection blocks:
  - Loopback addresses (127.0.0.0/8, ::1)
  - Private network ranges (RFC 1918, RFC 4193)
  - Link-local addresses (169.254.0.0/16, fe80::/10)
  - Cloud metadata endpoints (169.254.169.254, fd00:ec2::254)
  - Unresolvable hostnames

Webhook signing secrets are encrypted at rest with Fernet (AES-128-CBC +
HMAC-SHA256). The key is derived from ``WEBHOOK_SECRET_ENCRYPTION_KEY`` in
settings using PBKDF2-HMAC-SHA256 so the raw env value does not need to be
exactly 32 bytes.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import secrets
import socket
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.exceptions import AppError

# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback IPv4
    ipaddress.ip_network("::1/128"),  # loopback IPv6
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),  # link-local IPv4 / cloud metadata
    ipaddress.ip_network("fe80::/10"),  # link-local IPv6
    ipaddress.ip_network("fc00::/7"),  # unique local IPv6 (RFC 4193)
    ipaddress.ip_network("0.0.0.0/8"),  # "this" network
    ipaddress.ip_network("100.64.0.0/10"),  # shared address space (RFC 6598)
]

_MAX_URL_LENGTH = 2048


def _is_blocked_address(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global also rejects multicast, unspecified, reserved and other
    # special-purpose ranges beyond the explicitly listed private networks.
    return not ip.is_global or any(ip in net for net in _BLOCKED_NETWORKS)


def validate_webhook_url(url: str) -> str:
    """Validate a webhook URL and raise AppError if it fails SSRF checks.

    Returns the normalised URL on success.
    """
    if len(url) > _MAX_URL_LENGTH:
        raise AppError(
            "Webhook URL is too long.",
            code="invalid_webhook_url",
            status_code=422,
            details=[{"field": "webhook_url"}],
        ) from None

    try:
        parsed = urlparse(url)
        _ = parsed.port  # force validation of malformed ports
    except ValueError:
        raise AppError(
            "Webhook URL is malformed.",
            code="invalid_webhook_url",
            status_code=422,
            details=[{"field": "webhook_url"}],
        ) from None

    if parsed.scheme != "https":
        raise AppError(
            "Webhook URL must use HTTPS.",
            code="invalid_webhook_url",
            status_code=422,
            details=[{"field": "webhook_url"}],
        )

    hostname = parsed.hostname
    if not hostname or parsed.username or parsed.password:
        raise AppError(
            "Webhook URL must include a hostname.",
            code="invalid_webhook_url",
            status_code=422,
            details=[{"field": "webhook_url"}],
        )

    # Reject bare IP literals that are in blocked ranges.
    if _is_blocked_address(hostname):
        raise AppError(
            "Webhook URL points to a disallowed address.",
            code="ssrf_blocked",
            status_code=422,
            details=[{"field": "webhook_url"}],
        )

    # Resolve the hostname and check every returned address.
    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise AppError(
            "Webhook URL hostname could not be resolved.",
            code="invalid_webhook_url",
            status_code=422,
            details=[{"field": "webhook_url"}],
        ) from None

    for _family, _type, _proto, _canonname, sockaddr in results:
        addr = sockaddr[0]
        if _is_blocked_address(addr):
            raise AppError(
                "Webhook URL resolves to a disallowed address.",
                code="ssrf_blocked",
                status_code=422,
                details=[{"field": "webhook_url"}],
            )

    if not results:
        raise AppError(
            "Webhook URL hostname could not be resolved.",
            code="invalid_webhook_url",
            status_code=422,
            details=[{"field": "webhook_url"}],
        )

    return url


def validate_webhook_redirect(current_url: str, redirect_url: str) -> str:
    """Validate a redirect target before following it during future delivery.

    Delivery code must call this on every redirect and resolve the returned
    hostname again immediately before connecting. URL validation alone cannot
    prevent DNS rebinding if the HTTP client performs a second unrestricted
    DNS lookup.
    """
    from urllib.parse import urljoin

    target = urljoin(current_url, redirect_url)
    return validate_webhook_url(target)


# ---------------------------------------------------------------------------
# Webhook secret generation and encryption
# ---------------------------------------------------------------------------

WEBHOOK_SECRET_BYTES = 32


def _fernet() -> Fernet:
    """Derive a stable Fernet key from the configured encryption key."""
    raw = settings.webhook_secret_encryption_key.encode("utf-8")
    derived = hashlib.pbkdf2_hmac(
        "sha256", raw, b"asama-webhook-secret", iterations=100_000, dklen=32
    )
    key = base64.urlsafe_b64encode(derived)
    return Fernet(key)


def generate_webhook_secret() -> str:
    """Return a new high-entropy webhook signing secret (hex string)."""
    return secrets.token_hex(WEBHOOK_SECRET_BYTES)


def encrypt_webhook_secret(secret: str) -> str:
    """Encrypt a webhook secret for storage. Returns a Fernet token string."""
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_webhook_secret(token: str) -> str:
    """Decrypt a stored webhook secret. Raises ValueError on tampered data."""
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
