"""Shared input validation helpers.

Emails are canonicalised before they reach the database: stored addresses are
always lowercase, and the ``users.email`` unique constraint plus
``ck_users_email_lowercase`` make uniqueness case-insensitive.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

MAX_EMAIL_LENGTH = 320
MAX_EMAIL_LOCAL_LENGTH = 64

# Pragmatic, dependency-free address check. It rejects the shapes that matter
# (missing ``@``, whitespace, empty labels, overlong local part) without
# pretending to implement RFC 5322 in full.
_EMAIL_PATTERN = re.compile(
    r"^[a-z0-9!#$%&'*+/=?^_`{|}~.-]+@"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def normalize_email(value: str) -> str:
    """Trim and lowercase an email address, rejecting invalid input."""

    candidate = value.strip().lower()
    if len(candidate) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.fullmatch(candidate):
        raise ValueError("Enter a valid email address.")
    local_part, _, _domain = candidate.partition("@")
    if not local_part or len(local_part) > MAX_EMAIL_LOCAL_LENGTH:
        raise ValueError("Enter a valid email address.")
    if ".." in candidate:
        raise ValueError("Enter a valid email address.")
    return candidate


NormalizedEmail = Annotated[str, AfterValidator(normalize_email)]
