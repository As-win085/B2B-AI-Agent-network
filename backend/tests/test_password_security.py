"""ASAMA-103: password hashing, password policy and refresh-token helpers."""

from __future__ import annotations

import pytest

from app.core.security import (
    PASSWORD_MAX_LENGTH,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    password_policy_error,
    verify_password,
)

STRONG_PASSWORD = "correct horse battery staple"


def test_password_hash_never_contains_plaintext() -> None:
    encoded = hash_password(STRONG_PASSWORD)
    assert STRONG_PASSWORD not in encoded
    assert encoded.startswith("scrypt$")


def test_password_hash_is_salted() -> None:
    first = hash_password(STRONG_PASSWORD)
    second = hash_password(STRONG_PASSWORD)
    assert first != second
    assert verify_password(STRONG_PASSWORD, first)
    assert verify_password(STRONG_PASSWORD, second)


def test_verify_password_accepts_correct_password() -> None:
    assert verify_password(STRONG_PASSWORD, hash_password(STRONG_PASSWORD))


def test_verify_password_rejects_wrong_password() -> None:
    assert not verify_password("wrong password entirely", hash_password(STRONG_PASSWORD))


def test_verify_password_rejects_malformed_or_tampered_hash() -> None:
    assert not verify_password(STRONG_PASSWORD, "")
    assert not verify_password(STRONG_PASSWORD, "plaintext-password")
    assert not verify_password(STRONG_PASSWORD, "sha256$deadbeef")
    assert not verify_password(STRONG_PASSWORD, "scrypt$not-a-number$8$1$c2FsdA==$ZGlnZXN0")


def test_verify_password_rejects_out_of_bounds_cost_parameters() -> None:
    # A tampered row must not be able to force a huge allocation.
    oversized = "scrypt$999999999999$8$1$c2FsdA==$ZGlnZXN0"
    assert not verify_password(STRONG_PASSWORD, oversized)


def test_needs_rehash_reports_legacy_and_current_hashes() -> None:
    current = hash_password(STRONG_PASSWORD)
    assert needs_rehash(current) is False

    legacy = current.replace("$16384$", "$8192$", 1)
    assert needs_rehash(legacy) is True
    assert needs_rehash("not-a-hash") is True


@pytest.mark.parametrize(
    "password",
    [
        "",
        "short",
        " leading-space-here",
        "trailing-space-here ",
        "password123",
        "PASSWORD123",
    ],
)
def test_password_policy_rejects_weak_values(password: str) -> None:
    assert password_policy_error(password) is not None


def test_password_policy_rejects_overlong_password() -> None:
    assert password_policy_error("a" * (PASSWORD_MAX_LENGTH + 1)) is not None


def test_password_policy_accepts_long_passphrase() -> None:
    assert password_policy_error(STRONG_PASSWORD) is None
    assert password_policy_error("x" * PASSWORD_MAX_LENGTH) is None


def test_refresh_tokens_are_unique_and_hashed() -> None:
    first = generate_refresh_token()
    second = generate_refresh_token()
    assert first != second
    assert len(first) > 32

    digest = hash_refresh_token(first)
    assert len(digest) == 64
    assert first not in digest
    assert digest == hash_refresh_token(first)
    assert digest != hash_refresh_token(second)
