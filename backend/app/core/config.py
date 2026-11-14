"""Typed application configuration loaded from environment variables.

The repository-root ``.env`` file is used for local development. Real
environment variables always take precedence, which is what production
containers and CI use.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repository root
ROOT_DIR = Path(__file__).resolve().parents[3]

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    """Runtime configuration for the API, workers and scripts."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Asama.ai API"
    app_env: Environment = "local"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:5173"

    # Data stores
    database_url: str = Field(min_length=1)
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"

    # Authentication (Phase 3)
    jwt_secret_key: str = Field(min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Agent credentials / webhooks (Phase 4)
    webhook_secret_encryption_key: str = Field(min_length=16)
    webhook_timeout_seconds: int = 10
    webhook_max_attempts: int = 5

    # Embeddings / reranking (Phase 5)
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    openai_api_key: str = ""
    reranker_provider: str = "cohere"
    reranker_model: str = ""
    cohere_api_key: str = ""

    # Routing defaults (Phase 5)
    routing_top_k: int = 50
    routing_score_threshold: float = 0.75
    routing_max_recipients: int = 5

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()


settings = get_settings()
