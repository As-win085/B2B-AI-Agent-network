"""Security primitives: password hashing and opaque refresh tokens.

Password hashing uses ``hashlib.scrypt`` (stdlib, memory-hard) so no extra
dependency is introduced. Hashes are self-describing and versioned::

    scrypt$<n>$<r>$<p>$<base64 salt>$<base64 digest>

The parameters are stored with each hash, which allows re-tuning the cost later
without breaking existing logins (:func:`needs_rehash`).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# Deliberately small blocklist of the most abused values; the primary control is
# the length requirement (NIST SP 800-63B style, no composition rules).
_WEAK_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "123456789012",
        "qwertyuiop12",
        "letmein12345",
        "administrator",
        "iloveyou1234",
    }
)

_SCRYPT_N = 2**14  # ~16 MiB working memory per hash
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_SALT_BYTES = 16
_SCHEME = "scrypt"

# Bounds used when parsing a stored hash. A tampered database row must never be
# able to make verification allocate unbounded memory.
_MIN_N, _MAX_N = 2**12, 2**18
_MIN_R, _MAX_R = 1, 16
_MIN_P, _MAX_P = 1, 4

REFRESH_TOKEN_BYTES = 48


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def password_policy_error(password: str) -> str | None:
    """Return a human-readable policy violation, or ``None`` when acceptable."""

    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Password must be at most {PASSWORD_MAX_LENGTH} characters long."
    if password.strip() != password:
        return "Password must not start or end with whitespace."
    if not password.strip():
        return "Password must not be blank."
    if password.lower() in _WEAK_PASSWORDS:
        return "Password is too common."
    return None


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a per-password random salt."""

    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"{_SCHEME}${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64encode(salt)}${_b64encode(digest)}"


def _parse_hash(encoded: str) -> tuple[int, int, int, bytes, bytes] | None:
    try:
        scheme, n_raw, r_raw, p_raw, salt_raw, digest_raw = encoded.split("$")
        if scheme != _SCHEME:
            return None
        n, r, p = int(n_raw), int(r_raw), int(p_raw)
        if not (_MIN_N <= n <= _MAX_N and _MIN_R <= r <= _MAX_R and _MIN_P <= p <= _MAX_P):
            return None
        if n & (n - 1):
            return None  # scrypt requires a power of two
        return n, r, p, _b64decode(salt_raw), _b64decode(digest_raw)
    except (ValueError, TypeError, binascii.Error):
        return None


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time password verification against a stored hash."""

    parsed = _parse_hash(encoded)
    if parsed is None:
        return False
    n, r, p, salt, expected = parsed
    if not expected:
        return False
    candidate = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
    )
    return hmac.compare_digest(candidate, expected)


def needs_rehash(encoded: str) -> bool:
    """Return ``True`` when a stored hash predates the current cost settings."""

    parsed = _parse_hash(encoded)
    if parsed is None:
        return True
    n, r, p, _salt, _digest = parsed
    return (n, r, p) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P)


def generate_refresh_token() -> str:
    """Return a high-entropy opaque refresh token (never stored in plaintext)."""

    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """Return the SHA-256 hex digest used to look up a refresh token.

    Refresh tokens are 384-bit random secrets, so a fast hash is appropriate:
    there is no low-entropy input for an attacker to brute force. Slow password
    hashes would only add latency to every refresh.
    """

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(left: str, right: str) -> bool:
    """Compare two strings without leaking timing information."""

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
