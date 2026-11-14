"""Organization slug generation.

Slugs are human-readable tenant identifiers used in URLs. They must be unique,
so generation retries with a numeric suffix before falling back to randomness.
"""

from __future__ import annotations

import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.organizations.models import Organization

MAX_SLUG_LENGTH = 100
_BASE_SLUG_BUDGET = 90
_MAX_ATTEMPTS = 40


def slugify(value: str) -> str:
    """Convert free text into a URL-safe slug."""

    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:_BASE_SLUG_BUDGET] or "org"


def unique_slug(db: Session, value: str) -> str:
    """Return a slug that is not yet used by another organization."""

    base = slugify(value)
    if not _slug_exists(db, base):
        return base

    for attempt in range(2, _MAX_ATTEMPTS):
        candidate = f"{base[: _BASE_SLUG_BUDGET - 4]}-{attempt}"
        if not _slug_exists(db, candidate):
            return candidate

    candidate = f"{base[: _BASE_SLUG_BUDGET - 9]}-{uuid.uuid4().hex[:8]}"
    if _slug_exists(db, candidate):
        raise AppError(
            "Could not allocate an organization slug. Try a different name.",
            code="organization_slug_unavailable",
            status_code=409,
        )
    return candidate


def _slug_exists(db: Session, slug: str) -> bool:
    return db.scalar(select(Organization.id).where(Organization.slug == slug)) is not None
