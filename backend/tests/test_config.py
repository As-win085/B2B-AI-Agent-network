from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_missing_required_settings_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DATABASE_URL", "JWT_SECRET_KEY", "WEBHOOK_SECRET_ENCRYPTION_KEY"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_local_settings_use_secure_postgres_url() -> None:
    settings = Settings()

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in settings.database_url
    assert settings.routing_top_k == 50
    assert settings.routing_score_threshold == 0.75
