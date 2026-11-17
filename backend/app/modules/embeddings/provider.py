"""Embedding provider contract and OpenAI adapter."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import settings


class EmbeddingProviderError(Exception):
    """A safe, non-sensitive embedding failure suitable for API/task handling."""


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    provider: str
    model: str
    vector: list[float]


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> EmbeddingResult: ...


ClientFactory = Callable[..., Any]


def validate_embedding(values: object, dimensions: int) -> list[float]:
    """Validate and normalize one vector before it reaches persistence."""
    if not isinstance(values, list) or len(values) != dimensions:
        raise EmbeddingProviderError("The embedding provider returned an invalid vector size.")

    vector: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EmbeddingProviderError("The embedding provider returned an invalid vector value.")
        number = float(value)
        if not math.isfinite(number):
            raise EmbeddingProviderError(
                "The embedding provider returned a non-finite vector value."
            )
        vector.append(number)
    return vector


class OpenAIEmbeddingProvider:
    """OpenAI embeddings adapter using the configured model and dimensions."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        client_factory: ClientFactory = httpx.Client,
        timeout_seconds: float = 20,
    ) -> None:
        self._api_key = settings.openai_api_key if api_key is None else api_key
        self._model = settings.embedding_model if model is None else model
        self._dimensions = settings.embedding_dimensions if dimensions is None else dimensions
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    def embed(self, text: str) -> EmbeddingResult:
        if not self._api_key:
            raise EmbeddingProviderError("The embedding provider is not configured.")

        try:
            with self._client_factory(timeout=self._timeout_seconds) as client:
                response = client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "input": text,
                        "dimensions": self._dimensions,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                vector_values = payload["data"][0]["embedding"]
                response_model = payload.get("model", self._model)
        except EmbeddingProviderError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            # Avoid retaining provider responses, request text, or credentials in
            # errors and logs. A retry/task can use this stable failure class.
            raise EmbeddingProviderError("The embedding provider request failed.") from None

        vector = validate_embedding(vector_values, self._dimensions)
        return EmbeddingResult(provider=self.name, model=str(response_model), vector=vector)


def get_embedding_provider() -> EmbeddingProvider:
    provider = settings.embedding_provider.strip().lower()
    if provider != "openai":
        raise EmbeddingProviderError("The configured embedding provider is unsupported.")
    return OpenAIEmbeddingProvider()
